package com.oopsw.gatewayserver;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import jakarta.servlet.FilterChain;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class GatewayJwtFilterTest {

    private static final String ISSUER = "kosta-erp-account";
    private static final String AUDIENCE = "kosta-erp-api";
    private static final String SECRET =
        "0123456789abcdef0123456789abcdef";

    private GatewayJwtFilter filter;
    private Algorithm algorithm;

    @BeforeEach
    void setUp() {
        byte[] secretBytes = SECRET.getBytes(StandardCharsets.UTF_8);
        String secretBase64 = Base64.getEncoder()
            .encodeToString(secretBytes);
        algorithm = Algorithm.HMAC256(secretBytes);
        filter = new GatewayJwtFilter(secretBase64, ISSUER, AUDIENCE);
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "/account/auth/register",
        "/account/auth/login",
        "/account/auth/refresh",
        "/account/auth/logout",
        "/actuator/health",
        "/actuator/prometheus"
    })
    void 공개_경로는_토큰_없이_통과한다(String path) throws Exception {
        MockHttpServletRequest request =
            new MockHttpServletRequest("GET", path);
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertThat(response.getStatus()).isEqualTo(200);
    }

    @Test
    void OPTIONS_요청은_토큰_없이_통과한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "OPTIONS",
            "/orders/1"
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
    }

    @Test
    void 보호된_API에_토큰이_없으면_401을_반환한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/orders/1"
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(request, response);
    }

    @Test
    void 정상_AccessToken이면_요청을_통과시킨다() throws Exception {
        String token = createAccessToken(
            algorithm,
            ISSUER,
            AUDIENCE,
            Instant.now().plusSeconds(300)
        );
        MockHttpServletRequest request = protectedRequest(token);
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertThat(response.getStatus()).isEqualTo(200);
    }

    @Test
    void 다른_비밀키로_서명한_토큰은_401을_반환한다() throws Exception {
        byte[] otherSecret = "abcdefghijklmnopqrstuvwxyz123456"
            .getBytes(StandardCharsets.UTF_8);
        String token = createAccessToken(
            Algorithm.HMAC256(otherSecret),
            ISSUER,
            AUDIENCE,
            Instant.now().plusSeconds(300)
        );

        assertUnauthorized(token);
    }

    @Test
    void 만료된_토큰은_401을_반환한다() throws Exception {
        String token = createAccessToken(
            algorithm,
            ISSUER,
            AUDIENCE,
            Instant.now().minusSeconds(60)
        );

        assertUnauthorized(token);
    }

    @Test
    void issuer가_다른_토큰은_401을_반환한다() throws Exception {
        String token = createAccessToken(
            algorithm,
            "wrong-issuer",
            AUDIENCE,
            Instant.now().plusSeconds(300)
        );

        assertUnauthorized(token);
    }

    @Test
    void audience가_다른_토큰은_401을_반환한다() throws Exception {
        String token = createAccessToken(
            algorithm,
            ISSUER,
            "wrong-audience",
            Instant.now().plusSeconds(300)
        );

        assertUnauthorized(token);
    }

    @Test
    void RefreshToken은_Gateway를_통과할_수_없다() throws Exception {
        Instant now = Instant.now();
        String token = JWT.create()
            .withIssuer(ISSUER)
            .withAudience(AUDIENCE)
            .withSubject("1")
            .withIssuedAt(now)
            .withExpiresAt(now.plusSeconds(300))
            .withClaim("token_type", "refresh")
            .withJWTId("refresh-token-id")
            .sign(algorithm);

        assertUnauthorized(token);
    }

    private MockHttpServletRequest protectedRequest(String token) {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/orders/1"
        );
        request.addHeader(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        return request;
    }

    private String createAccessToken(
        Algorithm signingAlgorithm,
        String issuer,
        String audience,
        Instant expiresAt
    ) {
        Instant now = Instant.now();
        return JWT.create()
            .withIssuer(issuer)
            .withAudience(audience)
            .withSubject("1")
            .withIssuedAt(now)
            .withExpiresAt(expiresAt)
            .withClaim("token_type", "access")
            .withClaim("email", "user@example.com")
            .withClaim("role", "ROLE_USER")
            .sign(signingAlgorithm);
    }

    private void assertUnauthorized(String token) throws Exception {
        MockHttpServletRequest request = protectedRequest(token);
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(request, response);
    }
}
