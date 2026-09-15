package com.oopsw.foundation;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.oopsw.security.RsaJwtVerifier;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.filter.OncePerRequestFilter;
import tools.jackson.databind.ObjectMapper;

public class JwtAccessFilter extends OncePerRequestFilter {
    private final RsaJwtVerifier verifier;
    private final ObjectMapper mapper;

    public JwtAccessFilter(ObjectMapper mapper,
        @Value("${app.auth.public-key-directory}") String directory,
        @Value("${app.auth.issuer}") String issuer,
        @Value("${app.auth.audience}") String audience) {
        this.mapper = mapper;
        this.verifier = new RsaJwtVerifier(directory, issuer, audience);
    }
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return path.equals("/actuator/health") || path.equals("/actuator/prometheus")
            || path.equals("/error") || request.getMethod().equals("OPTIONS");
    }
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
        FilterChain chain) throws ServletException, IOException {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            reject(request, response, "AUTHENTICATION_REQUIRED");
            return;
        }
        try {
            var jwt = verifier.verifyAccess(header.substring(7).trim());
            long accountId = Long.parseLong(jwt.getSubject());
            if (accountId <= 0) throw new IllegalArgumentException();
            request.setAttribute("accountId", accountId);
        } catch (JWTVerificationException | IllegalArgumentException exception) {
            response.setHeader("Token-Status", "invalid");
            reject(request, response, "INVALID_ACCESS_TOKEN");
            return;
        }
        chain.doFilter(request, response);
    }
    private void reject(HttpServletRequest request, HttpServletResponse response, String code) throws IOException {
        response.setStatus(401);
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write(mapper.writeValueAsString(Map.of(
            "timestamp", Instant.now().toString(), "status", 401, "code", code,
            "message", "유효한 인증 정보가 필요합니다.", "path", request.getRequestURI(), "fieldErrors", List.of())));
    }
}
