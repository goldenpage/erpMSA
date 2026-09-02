package com.oopsw.inventoryservice.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.auth0.jwt.interfaces.JWTVerifier;
import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiErrorWriter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Base64;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    public static final String AUTHENTICATED_ACCOUNT =
        "authenticatedAccount";

    private final JWTVerifier verifier;
    private final ApiErrorWriter apiErrorWriter;

    public JwtAuthenticationFilter(
        ApiErrorWriter apiErrorWriter,
        @Value("${app.auth.secret-base64}") String secretBase64,
        @Value("${app.auth.issuer}") String issuer,
        @Value("${app.auth.audience}") String audience
    ) {
        this.apiErrorWriter = apiErrorWriter;
        byte[] secret;

        try {
            secret = Base64.getDecoder().decode(secretBase64);
        } catch (IllegalArgumentException exception) {
            throw new IllegalStateException(
                "JWT_SECRET_BASE64가 올바른 Base64 형식이 아닙니다.",
                exception
            );
        }

        if (secret.length < 32) {
            throw new IllegalStateException(
                "HS256 비밀키는 최소 32바이트 이상이어야 합니다."
            );
        }

        this.verifier = JWT.require(Algorithm.HMAC256(secret))
            .withIssuer(issuer)
            .withAudience(audience)
            .withClaim("token_type", "access")
            .withClaimPresence("sub")
            .withClaimPresence("email")
            .withClaimPresence("role")
            .acceptLeeway(30)
            .build();
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

        AuthenticatedAccount account;

        try {
            DecodedJWT jwt = verifier.verify(authorization.substring(7).trim());
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
