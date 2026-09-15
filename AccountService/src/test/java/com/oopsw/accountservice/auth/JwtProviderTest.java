package com.oopsw.accountservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.accountservice.entity.AccountEntity;
import com.oopsw.accountservice.entity.AccountStatus;
import java.time.Duration;
import com.oopsw.security.JwtTestKeys;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class JwtProviderTest {

    private static final Long ACCOUNT_ID = 1L;
    private static final String ISSUER = "kosta-erp-account";
    private static final String AUDIENCE = "kosta-erp-api";

    private JwtProvider jwtProvider;
    private AccountEntity account;

    @BeforeEach
    void setUp() {
        AuthProperties properties = new AuthProperties(
            ISSUER,
            AUDIENCE,
            JwtTestKeys.PRIMARY.publicDirectory(),
            JwtTestKeys.PRIMARY.kid(),
            JwtTestKeys.PRIMARY.privatePath(),
            Duration.ofMinutes(15),
            Duration.ofDays(14),
            false
        );
        jwtProvider = new JwtProvider(properties);

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
        ReflectionTestUtils.setField(account, "id", ACCOUNT_ID);
    }

    @Test
    void AccessToken에_필수_Claim이_포함된다() {
        String token = jwtProvider.createAccessToken(account);

        DecodedJWT jwt = jwtProvider.verifyAccessToken(token);

        assertThat(jwt.getIssuer()).isEqualTo(ISSUER);
        assertThat(jwt.getAudience()).containsExactly(AUDIENCE);
        assertThat(jwt.getSubject()).isEqualTo(ACCOUNT_ID.toString());
        assertThat(jwt.getClaim("token_type").asString()).isEqualTo("access");
        assertThat(jwt.getClaim("email").asString())
            .isEqualTo("user@example.com");
        assertThat(jwt.getClaim("businessId").asString())
            .isEqualTo("1234567890");
        assertThat(jwt.getClaim("role").asString()).isEqualTo("ROLE_USER");
        assertThat(Duration.between(
            jwt.getIssuedAt().toInstant(),
            jwt.getExpiresAt().toInstant()
        )).isEqualTo(Duration.ofMinutes(15));
    }

    @Test
    void RefreshToken에는_jti가_포함된다() {
        String token = jwtProvider.createRefreshToken(account);

        DecodedJWT jwt = jwtProvider.verifyRefreshToken(token);

        assertThat(jwt.getSubject()).isEqualTo(ACCOUNT_ID.toString());
        assertThat(jwt.getClaim("token_type").asString())
            .isEqualTo("refresh");
        assertThat(jwt.getId()).isNotBlank();
        assertThat(Duration.between(
            jwt.getIssuedAt().toInstant(),
            jwt.getExpiresAt().toInstant()
        )).isEqualTo(Duration.ofDays(14));
    }

    @Test
    void AccessToken을_RefreshToken으로_사용할_수_없다() {
        String accessToken = jwtProvider.createAccessToken(account);

        assertThatThrownBy(() -> jwtProvider.verifyRefreshToken(accessToken))
            .isInstanceOf(JWTVerificationException.class);
    }

    @Test
    void RefreshToken을_AccessToken으로_사용할_수_없다() {
        String refreshToken = jwtProvider.createRefreshToken(account);

        assertThatThrownBy(() -> jwtProvider.verifyAccessToken(refreshToken))
            .isInstanceOf(JWTVerificationException.class);
    }

    @Test
    void 공개키와_다른_개인키이면_시작하지_않는다() {
        AuthProperties properties = new AuthProperties(
            ISSUER, AUDIENCE, JwtTestKeys.PRIMARY.publicDirectory(), JwtTestKeys.PRIMARY.kid(),
            JwtTestKeys.OTHER.privatePath(), Duration.ofMinutes(15), Duration.ofDays(14), false);
        assertThatThrownBy(() -> new JwtProvider(properties))
            .isInstanceOf(IllegalStateException.class);
    }
}
