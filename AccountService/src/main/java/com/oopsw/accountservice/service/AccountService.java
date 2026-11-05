package com.oopsw.accountservice.service;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.accountservice.advice.dto.LoginRequest;
import com.oopsw.accountservice.advice.dto.RegisterRequest;
import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiException;
import com.oopsw.accountservice.auth.DummyPasswordHash;
import com.oopsw.accountservice.auth.JwtProvider;
import com.oopsw.accountservice.auth.LoginAttemptLimiter;
import com.oopsw.accountservice.auth.PasswordHashGate;
import com.oopsw.accountservice.auth.RefreshTokenStore;
import com.oopsw.accountservice.entity.AccountEntity;
import com.oopsw.accountservice.entity.AccountRepository;
import com.oopsw.accountservice.entity.AccountStatus;
import com.oopsw.accountservice.outbox.AccountEventOutbox;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@RequiredArgsConstructor
public class AccountService {

    private final AccountRepository accountRepository;
    private final EmailNormalizer emailNormalizer;
    private final PasswordEncoder passwordEncoder;
    private final JwtProvider jwtProvider;
    private final RefreshTokenStore refreshTokenStore;
    private final AccountEventOutbox accountEventOutbox;
    private final PasswordHashGate passwordHashGate;
    private final TransactionTemplate transactionTemplate;
    private final LoginAttemptLimiter loginAttemptLimiter;
    private final DummyPasswordHash dummyPasswordHash;

    public RegisterResponse register(RegisterRequest request, String clientAddress) {
        // IP 기준 제한은 다른 모든 처리보다 먼저 한다.
        loginAttemptLimiter.checkRegister(clientAddress);

        String email = emailNormalizer.normalize(request.email());

        // 명백한 중복은 BCrypt 계산 전에 거절한다.
        ensureAvailable(email, request.businessId());

        // BCrypt는 DB 연결을 잡지 않은 상태(트랜잭션 밖)에서 계산한다.
        // 트랜잭션 안에서 계산하면 해시 시간 동안 연결을 점유해 연결 풀이 병목이 될 수 있다.
        String passwordHash = passwordHashGate.run(
            () -> passwordEncoder.encode(request.password())
        );

        return transactionTemplate.execute(status -> {
            // 해시 계산 중 같은 정보로 가입이 끝났을 수 있으므로 다시 확인한다.
            // 동시에 통과한 요청은 DB 유일 제약이 거절한다(ACCOUNT_CONFLICT).
            ensureAvailable(email, request.businessId());

            AccountEntity account = AccountEntity.register(
                email,
                request.businessId(),
                passwordHash,
                request.name(),
                request.phone(),
                request.storeName(),
                request.storeType(),
                request.storeCategory(),
                request.marketingAgreed(),
                AccountStatus.ACTIVE
            );

            AccountEntity saved = accountRepository.saveAndFlush(account);
            accountEventOutbox.enqueueRegistered(saved);

            return new RegisterResponse(
                saved.getId(),
                saved.getEmail(),
                saved.getReviewStatus().name()
            );
        });
    }

    private void ensureAvailable(String email, String businessId) {
        if (accountRepository.existsByEmail(email)) {
            throw new ApiException(ApiErrorCode.EMAIL_ALREADY_EXISTS);
        }

        if (accountRepository.existsByBusinessId(businessId)) {
            throw new ApiException(
                ApiErrorCode.BUSINESS_ID_ALREADY_EXISTS
            );
        }
    }

    public IssuedTokens login(LoginRequest request, String clientAddress) {
        String email = emailNormalizer.normalize(request.email());

        // 시도 제한은 DB 조회·BCrypt보다 먼저 검사한다. 막힌 시도는 CPU를 쓰지 않는다.
        loginAttemptLimiter.checkLogin(clientAddress, email);

        AccountEntity account = accountRepository.findByEmail(email).orElse(null);

        // 없는 이메일도 같은 비용의 BCrypt를 수행하고 같은 방식으로 실패를 센다.
        // 응답시간과 시도 제한 동작으로 가입 여부를 알 수 없게 하기 위해서다.
        String expectedHash = account == null ? dummyPasswordHash.value() : account.getPwHash();
        boolean matches = passwordHashGate.run(
            () -> passwordEncoder.matches(
                request.password(),
                expectedHash
            )
        );

        if (account == null || !matches) {
            loginAttemptLimiter.recordFailure(email);
            throw badCredentials();
        }

        loginAttemptLimiter.recordSuccess(email);
        validateLoginStatus(account);

        return issueTokens(account);
    }

    public IssuedTokens refresh(String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            throw invalidRefreshToken();
        }

        DecodedJWT decodedJWT;

        try {
            decodedJWT = jwtProvider.verifyRefreshToken(refreshToken);
        } catch (JWTVerificationException exception) {
            throw invalidRefreshToken();
        }

        Long jwtAccountId;

        try {
            jwtAccountId = Long.valueOf(decodedJWT.getSubject());
        } catch (NumberFormatException exception) {
            throw invalidRefreshToken();
        }

        /*
         * GETDEL 처리:
         * 같은 Refresh Token을 두 번째 사용하면 null이 반환된다.
         */
        Long redisAccountId = refreshTokenStore.consume(refreshToken);

        if (redisAccountId == null ||
            !redisAccountId.equals(jwtAccountId)) {
            throw invalidRefreshToken();
        }

        AccountEntity account = accountRepository.findById(jwtAccountId)
            .orElseThrow(this::invalidRefreshToken);

        validateLoginStatus(account);

        // Access Token과 Refresh Token 모두 회전
        return issueTokens(account);
    }

    public void logout(String refreshToken) {
        refreshTokenStore.revoke(refreshToken);
    }

    private IssuedTokens issueTokens(AccountEntity account) {
        String accessToken = jwtProvider.createAccessToken(account);
        String refreshToken = jwtProvider.createRefreshToken(account);

        refreshTokenStore.save(
            refreshToken,
            account.getId(),
            jwtProvider.getRefreshTtl()
        );

        return new IssuedTokens(
            accessToken,
            jwtProvider.getAccessTokenExpiresInSeconds(),
            refreshToken
        );
    }

    private void validateLoginStatus(AccountEntity account) {
        if (!account.canLogin()) {
            throw new ApiException(ApiErrorCode.ACCOUNT_LOGIN_FORBIDDEN);
        }
    }

    private ApiException badCredentials() {
        return new ApiException(ApiErrorCode.INVALID_CREDENTIALS);
    }

    private ApiException invalidRefreshToken() {
        return new ApiException(ApiErrorCode.INVALID_REFRESH_TOKEN);
    }

    public record RegisterResponse(
        Long accountId,
        String email,
        String status
    ) {
    }

    public record IssuedTokens(
        String accessToken,
        long accessTokenExpiresIn,
        String refreshToken
    ) {
    }
}
