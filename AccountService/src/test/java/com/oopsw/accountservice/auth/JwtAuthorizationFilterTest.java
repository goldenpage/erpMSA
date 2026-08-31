package com.oopsw.accountservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.oopsw.accountservice.api.ApiErrorWriter;
import com.oopsw.accountservice.entity.AccountEntity;
import com.oopsw.accountservice.entity.AccountStatus;
import jakarta.servlet.FilterChain;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class JwtAuthorizationFilterTest {

    private static final String ISSUER = "kosta-erp-account";
    private static final String AUDIENCE = "kosta-erp-api";

    private JwtProvider jwtProvider;
    private JwtAuthorizationFilter filter;
    private AccountEntity account;
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        jwtProvider = createProvider(
            "0123456789abcdef0123456789abcdef"
        );
        objectMapper = new ObjectMapper();
        filter = new JwtAuthorizationFilter(
            jwtProvider,
            new ApiErrorWriter(objectMapper)
        );
        account = AccountEntity.register(
            "user@example.com",
            "1234567890",
            "encoded-password",
            "홍길동",
            "01012345678",
            "테스트 매장",
            "RESTAURANT",
            "KOREAN",
            true,
            AccountStatus.ACTIVE
        );
        ReflectionTestUtils.setField(account, "id", 1L);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void 토큰이_없으면_다음_필터로_진행한다() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/account/auth/me"
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication())
            .isNull();
    }

    @Test
    void 정상_AccessToken이면_인증정보를_생성한다() throws Exception {
        MockHttpServletRequest request = authorizedRequest(
            jwtProvider.createAccessToken(account)
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        Authentication authentication = SecurityContextHolder.getContext()
            .getAuthentication();
        assertThat(authentication).isNotNull();
        assertThat(authentication.isAuthenticated()).isTrue();
        assertThat(authentication.getPrincipal())
            .isEqualTo(new AuthPrincipal(1L, "user@example.com"));
        assertThat(authentication.getAuthorities())
            .extracting(GrantedAuthority::getAuthority)
            .containsExactly("ROLE_USER");
    }

    @Test
    void 변조된_AccessToken이면_401을_반환한다() throws Exception {
        JwtProvider anotherProvider = createProvider(
            "abcdefghijklmnopqrstuvwxyz123456"
        );
        MockHttpServletRequest request = authorizedRequest(
            anotherProvider.createAccessToken(account)
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getHeader("Token-Status")).isEqualTo("invalid");
        assertThat(response.getContentType()).startsWith("application/json");

        JsonNode body = objectMapper.readTree(
            response.getContentAsString()
        );
        assertThat(body.get("code").stringValue())
            .isEqualTo("INVALID_ACCESS_TOKEN");
        assertThat(body.get("path").stringValue())
            .isEqualTo("/account/auth/me");
        assertThat(body.get("fieldErrors").isArray()).isTrue();
        verify(chain, never()).doFilter(request, response);
    }

    private MockHttpServletRequest authorizedRequest(String token) {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/account/auth/me"
        );
        request.addHeader(
            HttpHeaders.AUTHORIZATION,
            JwtProvider.PREFIX + token
        );
        return request;
    }

    private JwtProvider createProvider(String secret) {
        String secretBase64 = Base64.getEncoder().encodeToString(
            secret.getBytes(StandardCharsets.UTF_8)
        );
        return new JwtProvider(new AuthProperties(
            ISSUER,
            AUDIENCE,
            secretBase64,
            Duration.ofMinutes(15),
            Duration.ofDays(14),
            false
        ));
    }
}
