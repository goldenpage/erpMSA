package com.oopsw.accountservice.auth;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

@RequiredArgsConstructor
public class JwtAuthorizationFilter extends OncePerRequestFilter {

    private final JwtProvider jwtProvider;

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {

        String token = resolveAccessToken(request);

        if (token == null) {
            filterChain.doFilter(request, response);
            return;
        }

        try {
            DecodedJWT jwt = jwtProvider.verifyAccessToken(token);

            Long accountId = Long.valueOf(jwt.getSubject());
            String email = jwt.getClaim("email").asString();
            String role = jwt.getClaim("role").asString();

            if (email == null || role == null || !role.startsWith("ROLE_")) {
                throw new JWTVerificationException(
                    "Access Token 필수 Claim이 올바르지 않습니다."
                );
            }

            AuthPrincipal principal = new AuthPrincipal(accountId, email);

            UsernamePasswordAuthenticationToken authentication =
                new UsernamePasswordAuthenticationToken(
                    principal,
                    null,
                    List.of(new SimpleGrantedAuthority(role))
                );

            SecurityContextHolder.getContext()
                .setAuthentication(authentication);

            filterChain.doFilter(request, response);

        } catch (JWTVerificationException | NumberFormatException exception) {
            SecurityContextHolder.clearContext();
            response.setHeader("Token-Status", "invalid");
            response.sendError(
                HttpServletResponse.SC_UNAUTHORIZED,
                "유효하지 않은 Access Token입니다."
            );
        }
    }

    private String resolveAccessToken(HttpServletRequest request) {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);

        if (header == null || !header.startsWith(JwtProvider.PREFIX)) {
            return null;
        }

        String token = header.substring(JwtProvider.PREFIX.length()).trim();
        return token.isBlank() ? null : token;
    }
}