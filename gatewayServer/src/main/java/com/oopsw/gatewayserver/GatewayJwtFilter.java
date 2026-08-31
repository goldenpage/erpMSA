package com.oopsw.gatewayserver;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.JWTVerifier;
import com.oopsw.gatewayserver.api.ApiErrorCode;
import com.oopsw.gatewayserver.api.ApiErrorWriter;
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
public class GatewayJwtFilter extends OncePerRequestFilter {

    private final JWTVerifier verifier;
    private final ApiErrorWriter apiErrorWriter;

    public GatewayJwtFilter(
        ApiErrorWriter apiErrorWriter,
        @Value("${app.auth.secret-base64}") String secretBase64,
        @Value("${app.auth.issuer}") String issuer,
        @Value("${app.auth.audience}") String audience
    ) {
        this.apiErrorWriter = apiErrorWriter;
        byte[] secret = Base64.getDecoder().decode(secretBase64);

        if (secret.length < 32) {
            throw new IllegalStateException(
                "JWT 비밀키는 최소 32바이트 이상이어야 합니다."
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
            verifier.verify(token);
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
