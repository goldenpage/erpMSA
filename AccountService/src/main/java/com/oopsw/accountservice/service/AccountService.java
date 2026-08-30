package com.oopsw.accountservice.service;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.accountservice.advice.dto.LoginRequest;
import com.oopsw.accountservice.advice.dto.RegisterRequest;
import com.oopsw.accountservice.auth.JwtProvider;
import com.oopsw.accountservice.auth.RefreshTokenStore;
import com.oopsw.accountservice.entity.AccountEntity;
import com.oopsw.accountservice.entity.AccountRepository;
import com.oopsw.accountservice.entity.AccountStatus;
import com.oopsw.accountservice.outbox.AccountEventOutbox;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class AccountService {

    private final AccountRepository accountRepository;
    private final EmailNormalizer emailNormalizer;
    private final PasswordEncoder passwordEncoder;
    private final JwtProvider jwtProvider;
    private final RefreshTokenStore refreshTokenStore;
    private final AccountEventOutbox accountEventOutbox;

    @Transactional
    public RegisterResponse register(RegisterRequest request) {
        String email = emailNormalizer.normalize(request.email());

        if (accountRepository.existsByEmail(email)) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT,
                "이미 가입된 이메일입니다."
            );
        }

        if (accountRepository.existsByBusinessId(request.businessId())) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT,
                "이미 등록된 사업자번호입니다."
            );
        }

        AccountEntity account = AccountEntity.register(
            email,
            request.businessId(),
            passwordEncoder.encode(request.password()),
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
    }

    public IssuedTokens login(LoginRequest request) {
        String email = emailNormalizer.normalize(request.email());

        AccountEntity account = accountRepository.findByEmail(email)
            .orElseThrow(this::badCredentials);

        if (!passwordEncoder.matches(
            request.password(),
            account.getPwHash()
        )) {
            throw badCredentials();
        }

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
            throw new ResponseStatusException(
                HttpStatus.FORBIDDEN,
                "로그인할 수 없는 계정 상태입니다."
            );
        }
    }

    private ResponseStatusException badCredentials() {
        return new ResponseStatusException(
            HttpStatus.UNAUTHORIZED,
            "이메일 또는 비밀번호가 올바르지 않습니다."
        );
    }

    private ResponseStatusException invalidRefreshToken() {
        return new ResponseStatusException(
            HttpStatus.UNAUTHORIZED,
            "유효하지 않은 Refresh Token입니다."
        );
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
