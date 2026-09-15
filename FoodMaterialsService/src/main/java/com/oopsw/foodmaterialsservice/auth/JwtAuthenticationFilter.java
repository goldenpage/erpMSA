package com.oopsw.foodmaterialsservice.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.foodmaterialsservice.api.ApiErrorCode;
import com.oopsw.foodmaterialsservice.api.ApiErrorWriter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import com.oopsw.security.RsaJwtVerifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    public static final String AUTHENTICATED_ACCOUNT =
        "authenticatedAccount";

    private final RsaJwtVerifier verifier;
    private final ApiErrorWriter apiErrorWriter;

    public JwtAuthenticationFilter(
        ApiErrorWriter apiErrorWriter,
        @Value("${app.auth.public-key-directory}") String publicKeyDirectory,
        @Value("${app.auth.issuer}") String issuer,
        @Value("${app.auth.audience}") String audience
    ) {
        this.apiErrorWriter = apiErrorWriter;
        this.verifier = new RsaJwtVerifier(publicKeyDirectory, issuer, audience);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return HttpMethod.OPTIONS.matches(request.getMethod())
            || path.equals("/actuator/health")
            || path.equals("/actuator/prometheus")
            || path.equals("/error");
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {
        String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);

        if (authorization == null || !authorization.startsWith("Bearer ")) {
            apiErrorWriter.write(
                request,
                response,
                ApiErrorCode.AUTHENTICATION_REQUIRED
            );
            return;
        }

        String token = authorization.substring(7).trim();
        AuthenticatedAccount account;

        try {
            DecodedJWT jwt = verifier.verifyAccess(token);
            String email = jwt.getClaim("email").asString();
            String role = jwt.getClaim("role").asString();

            if (email == null || email.isBlank() ||
                role == null || role.isBlank()) {
                writeInvalidToken(request, response);
                return;
            }

            account = new AuthenticatedAccount(
                Long.valueOf(jwt.getSubject()),
                email,
                role
            );
        } catch (JWTVerificationException | IllegalArgumentException exception) {
            writeInvalidToken(request, response);
            return;
        }

        request.setAttribute(AUTHENTICATED_ACCOUNT, account);
        filterChain.doFilter(request, response);
    }

    private void writeInvalidToken(
        HttpServletRequest request,
        HttpServletResponse response
    ) throws IOException {
        response.setHeader("Token-Status", "invalid");
        apiErrorWriter.write(
            request,
            response,
            ApiErrorCode.INVALID_ACCESS_TOKEN
        );
    }
}
