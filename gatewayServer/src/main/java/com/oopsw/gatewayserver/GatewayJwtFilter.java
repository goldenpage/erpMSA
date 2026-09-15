package com.oopsw.gatewayserver;

import com.auth0.jwt.JWT;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.oopsw.gatewayserver.api.ApiErrorCode;
import com.oopsw.gatewayserver.api.ApiErrorWriter;
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
public class GatewayJwtFilter extends OncePerRequestFilter {

    private final RsaJwtVerifier verifier;
    private final ApiErrorWriter apiErrorWriter;

    public GatewayJwtFilter(
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
            || path.equals("/account/auth/register")
            || path.equals("/account/auth/login")
            || path.equals("/account/auth/refresh")
            || path.equals("/account/auth/logout")
            || path.equals("/actuator/health")
            || path.equals("/actuator/prometheus");
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {
        String authorization =
            request.getHeader(HttpHeaders.AUTHORIZATION);

        if (authorization == null ||
            !authorization.startsWith("Bearer ")) {
            apiErrorWriter.write(
                request,
                response,
                ApiErrorCode.AUTHENTICATION_REQUIRED
            );
            return;
        }

        String token = authorization.substring(7).trim();

        try {
            verifier.verifyAccess(token);
            filterChain.doFilter(request, response);
        } catch (JWTVerificationException exception) {
            response.setHeader("Token-Status", "invalid");
            apiErrorWriter.write(
                request,
                response,
                ApiErrorCode.INVALID_ACCESS_TOKEN
            );
        }
    }
}
