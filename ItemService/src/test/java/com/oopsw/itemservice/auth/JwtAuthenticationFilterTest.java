package com.oopsw.itemservice.auth;

import static org.assertj.core.api.Assertions.assertThat;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.oopsw.itemservice.api.ApiErrorWriter;
import java.time.Instant;
import java.util.Base64;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import tools.jackson.databind.ObjectMapper;

class JwtAuthenticationFilterTest {

    private static final byte[] SECRET =
        "0123456789abcdef0123456789abcdef".getBytes();
    private static final String SECRET_BASE64 =
        Base64.getEncoder().encodeToString(SECRET);

    private JwtAuthenticationFilter filter;

    @BeforeEach
    void setUp() {
        filter = new JwtAuthenticationFilter(
            new ApiErrorWriter(new ObjectMapper()),
            SECRET_BASE64,
            "issuer",
            "audience"
        );
    }

    @Test
    void 유효한_토큰이면_계정정보를_요청에_저장한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/items"
        );
        request.addHeader(HttpHeaders.AUTHORIZATION, "Bearer " + token(10L));
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean continued = new AtomicBoolean();

        filter.doFilter(request, response, (req, res) -> {
            continued.set(true);
            var account = (AuthenticatedAccount) req.getAttribute(
                JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT
            );
            assertThat(account.accountId()).isEqualTo(10L);
            assertThat(account.email()).isEqualTo("owner@example.com");
            assertThat(account.role()).isEqualTo("ROLE_USER");
        });

        assertThat(continued).isTrue();
        assertThat(response.getStatus()).isEqualTo(200);
    }

    @Test
    void 토큰이_없으면_표준_401_응답을_반환한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/items"
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean continued = new AtomicBoolean();

        filter.doFilter(request, response, (req, res) -> continued.set(true));

        assertThat(continued).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getContentAsString())
            .contains("\"code\":\"AUTHENTICATION_REQUIRED\"")
            .contains("\"path\":\"/items\"");
    }

    @Test
    void 잘못된_토큰이면_표준_401_응답을_반환한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/items"
        );
        request.addHeader(HttpHeaders.AUTHORIZATION, "Bearer invalid");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) -> {
            throw new AssertionError("필터 체인이 실행되면 안 됩니다.");
        });

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getHeader("Token-Status")).isEqualTo("invalid");
        assertThat(response.getContentAsString())
            .contains("\"code\":\"INVALID_ACCESS_TOKEN\"");
    }

    @Test
    void Actuator_상태확인은_토큰없이_통과한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/actuator/health"
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean continued = new AtomicBoolean();

        filter.doFilter(request, response, (req, res) -> continued.set(true));

        assertThat(continued).isTrue();
    }

    private String token(Long accountId) {
        Instant now = Instant.now();
        return JWT.create()
            .withIssuer("issuer")
            .withAudience("audience")
            .withSubject(accountId.toString())
            .withIssuedAt(now)
            .withExpiresAt(now.plusSeconds(300))
            .withClaim("token_type", "access")
            .withClaim("email", "owner@example.com")
            .withClaim("role", "ROLE_USER")
            .sign(Algorithm.HMAC256(SECRET));
    }
}
