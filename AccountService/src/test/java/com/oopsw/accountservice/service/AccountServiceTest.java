package com.oopsw.accountservice.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.accountservice.advice.dto.LoginRequest;
import com.oopsw.accountservice.advice.dto.RegisterRequest;
import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiException;
import com.oopsw.accountservice.auth.JwtProvider;
import com.oopsw.accountservice.auth.RefreshTokenStore;
import com.oopsw.accountservice.entity.AccountEntity;
import com.oopsw.accountservice.entity.AccountRepository;
import com.oopsw.accountservice.entity.AccountRole;
import com.oopsw.accountservice.entity.AccountStatus;
import com.oopsw.accountservice.outbox.AccountEventOutbox;
import java.time.Duration;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class AccountServiceTest {

    private static final Long ACCOUNT_ID = 1L;
    private static final String EMAIL = "User@Example.com";
    private static final String NORMALIZED_EMAIL = "user@example.com";
    private static final String BUSINESS_ID = "1234567890";
    private static final String PASSWORD = "password123!";
    private static final String PASSWORD_HASH = "encoded-password";
    private static final String ACCESS_TOKEN = "access-token";
    private static final String REFRESH_TOKEN = "refresh-token";
    private static final String OLD_REFRESH_TOKEN = "old-refresh-token";
    private static final Duration REFRESH_TTL = Duration.ofDays(14);

    @Mock
    private AccountRepository accountRepository;

    @Mock
    private EmailNormalizer emailNormalizer;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private JwtProvider jwtProvider;

    @Mock
    private RefreshTokenStore refreshTokenStore;

    @Mock
    private AccountEventOutbox accountEventOutbox;

    @InjectMocks
    private AccountService accountService;

    private RegisterRequest registerRequest;
    private LoginRequest loginRequest;

    @BeforeEach
    void setUp() {
        registerRequest = new RegisterRequest(
            EMAIL,
            BUSINESS_ID,
            PASSWORD,
            "홍길동",
            "01012345678",
            "테스트 매장",
            "RESTAURANT",
            "KOREAN",
            true
        );

        loginRequest = new LoginRequest(EMAIL, PASSWORD);
    }

    @Test
    void 회원가입에_성공한다() {
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.existsByEmail(NORMALIZED_EMAIL))
            .thenReturn(false);
        when(accountRepository.existsByBusinessId(BUSINESS_ID))
            .thenReturn(false);
        when(passwordEncoder.encode(PASSWORD))
            .thenReturn(PASSWORD_HASH);
        when(accountRepository.saveAndFlush(any(AccountEntity.class)))
            .thenAnswer(invocation -> {
                AccountEntity account = invocation.getArgument(0);
                ReflectionTestUtils.setField(account, "id", ACCOUNT_ID);
                return account;
            });

        AccountService.RegisterResponse response =
            accountService.register(registerRequest);

        assertThat(response.accountId()).isEqualTo(ACCOUNT_ID);
        assertThat(response.email()).isEqualTo(NORMALIZED_EMAIL);
        assertThat(response.status()).isEqualTo("ACTIVE");

        ArgumentCaptor<AccountEntity> captor =
            ArgumentCaptor.forClass(AccountEntity.class);
        verify(accountRepository).saveAndFlush(captor.capture());

        AccountEntity savedAccount = captor.getValue();
        assertThat(savedAccount.getEmail()).isEqualTo(NORMALIZED_EMAIL);
        assertThat(savedAccount.getBusinessId()).isEqualTo(BUSINESS_ID);
        assertThat(savedAccount.getPwHash()).isEqualTo(PASSWORD_HASH);
        assertThat(savedAccount.getRole()).isEqualTo(AccountRole.ROLE_USER);
        assertThat(savedAccount.getReviewStatus())
            .isEqualTo(AccountStatus.ACTIVE);
        verify(passwordEncoder).encode(PASSWORD);
        verify(accountEventOutbox).enqueueRegistered(savedAccount);
    }

    @Test
    void 이메일이_중복되면_회원가입에_실패한다() {
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.existsByEmail(NORMALIZED_EMAIL))
            .thenReturn(true);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.register(registerRequest)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.EMAIL_ALREADY_EXISTS);
        verify(accountRepository, never())
            .saveAndFlush(any(AccountEntity.class));
        verifyNoInteractions(passwordEncoder);
        verifyNoInteractions(accountEventOutbox);
    }

    @Test
    void 사업자번호가_중복되면_회원가입에_실패한다() {
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.existsByEmail(NORMALIZED_EMAIL))
            .thenReturn(false);
        when(accountRepository.existsByBusinessId(BUSINESS_ID))
            .thenReturn(true);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.register(registerRequest)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.BUSINESS_ID_ALREADY_EXISTS);
        verify(accountRepository, never())
            .saveAndFlush(any(AccountEntity.class));
        verifyNoInteractions(passwordEncoder);
        verifyNoInteractions(accountEventOutbox);
    }

    @Test
    void 로그인에_성공하면_토큰을_발급한다() {
        AccountEntity account = createAccount(AccountStatus.ACTIVE);
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.findByEmail(NORMALIZED_EMAIL))
            .thenReturn(Optional.of(account));
        when(passwordEncoder.matches(PASSWORD, PASSWORD_HASH))
            .thenReturn(true);
        prepareTokenIssue(account);

        AccountService.IssuedTokens tokens =
            accountService.login(loginRequest);

        assertThat(tokens.accessToken()).isEqualTo(ACCESS_TOKEN);
        assertThat(tokens.accessTokenExpiresIn()).isEqualTo(900L);
        assertThat(tokens.refreshToken()).isEqualTo(REFRESH_TOKEN);
        verify(refreshTokenStore).save(
            REFRESH_TOKEN,
            ACCOUNT_ID,
            REFRESH_TTL
        );
    }

    @Test
    void 비밀번호가_틀리면_로그인에_실패한다() {
        AccountEntity account = createAccount(AccountStatus.ACTIVE);
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.findByEmail(NORMALIZED_EMAIL))
            .thenReturn(Optional.of(account));
        when(passwordEncoder.matches(PASSWORD, PASSWORD_HASH))
            .thenReturn(false);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.login(loginRequest)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.INVALID_CREDENTIALS);
        verifyNoInteractions(jwtProvider, refreshTokenStore);
    }

    @Test
    void 존재하지_않는_계정은_로그인에_실패한다() {
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.findByEmail(NORMALIZED_EMAIL))
            .thenReturn(Optional.empty());

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.login(loginRequest)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.INVALID_CREDENTIALS);
        verifyNoInteractions(passwordEncoder, jwtProvider, refreshTokenStore);
    }

    @Test
    void 정지된_계정은_로그인할_수_없다() {
        AccountEntity account = createAccount(AccountStatus.SUSPENDED);
        when(emailNormalizer.normalize(EMAIL))
            .thenReturn(NORMALIZED_EMAIL);
        when(accountRepository.findByEmail(NORMALIZED_EMAIL))
            .thenReturn(Optional.of(account));
        when(passwordEncoder.matches(PASSWORD, PASSWORD_HASH))
            .thenReturn(true);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.login(loginRequest)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.ACCOUNT_LOGIN_FORBIDDEN);
        verifyNoInteractions(jwtProvider, refreshTokenStore);
    }

    @Test
    void RefreshToken으로_토큰을_재발급한다() {
        AccountEntity account = createAccount(AccountStatus.ACTIVE);
        DecodedJWT decodedJWT = mock(DecodedJWT.class);
        when(jwtProvider.verifyRefreshToken(OLD_REFRESH_TOKEN))
            .thenReturn(decodedJWT);
        when(decodedJWT.getSubject()).thenReturn(ACCOUNT_ID.toString());
        when(refreshTokenStore.consume(OLD_REFRESH_TOKEN))
            .thenReturn(ACCOUNT_ID);
        when(accountRepository.findById(ACCOUNT_ID))
            .thenReturn(Optional.of(account));
        prepareTokenIssue(account);

        AccountService.IssuedTokens tokens =
            accountService.refresh(OLD_REFRESH_TOKEN);

        assertThat(tokens.accessToken()).isEqualTo(ACCESS_TOKEN);
        assertThat(tokens.refreshToken()).isEqualTo(REFRESH_TOKEN);
        verify(refreshTokenStore).consume(OLD_REFRESH_TOKEN);
        verify(refreshTokenStore).save(
            REFRESH_TOKEN,
            ACCOUNT_ID,
            REFRESH_TTL
        );
    }

    @Test
    void 이미_사용한_RefreshToken은_재사용할_수_없다() {
        DecodedJWT decodedJWT = mock(DecodedJWT.class);
        when(jwtProvider.verifyRefreshToken(OLD_REFRESH_TOKEN))
            .thenReturn(decodedJWT);
        when(decodedJWT.getSubject()).thenReturn(ACCOUNT_ID.toString());
        when(refreshTokenStore.consume(OLD_REFRESH_TOKEN))
            .thenReturn(null);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.refresh(OLD_REFRESH_TOKEN)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.INVALID_REFRESH_TOKEN);
        verify(accountRepository, never()).findById(ACCOUNT_ID);
    }

    @Test
    void 변조된_RefreshToken으로_재발급할_수_없다() {
        when(jwtProvider.verifyRefreshToken(OLD_REFRESH_TOKEN))
            .thenThrow(new JWTVerificationException("invalid token"));

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.refresh(OLD_REFRESH_TOKEN)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.INVALID_REFRESH_TOKEN);
        verifyNoInteractions(accountRepository, refreshTokenStore);
    }

    @Test
    void JWT와_Redis의_계정_ID가_다르면_재발급할_수_없다() {
        DecodedJWT decodedJWT = mock(DecodedJWT.class);
        when(jwtProvider.verifyRefreshToken(OLD_REFRESH_TOKEN))
            .thenReturn(decodedJWT);
        when(decodedJWT.getSubject()).thenReturn(ACCOUNT_ID.toString());
        when(refreshTokenStore.consume(OLD_REFRESH_TOKEN)).thenReturn(2L);

        ApiException exception = assertThrows(
            ApiException.class,
            () -> accountService.refresh(OLD_REFRESH_TOKEN)
        );

        assertThat(exception.errorCode())
            .isEqualTo(ApiErrorCode.INVALID_REFRESH_TOKEN);
        verify(accountRepository, never()).findById(ACCOUNT_ID);
    }

    @Test
    void 로그아웃하면_RefreshToken을_폐기한다() {
        accountService.logout(REFRESH_TOKEN);

        verify(refreshTokenStore).revoke(REFRESH_TOKEN);
    }

    private AccountEntity createAccount(AccountStatus status) {
        AccountEntity account = AccountEntity.register(
            NORMALIZED_EMAIL,
            BUSINESS_ID,
            PASSWORD_HASH,
            "홍길동",
            "01012345678",
            "테스트 매장",
            "RESTAURANT",
            "KOREAN",
            true,
            status
        );
        ReflectionTestUtils.setField(account, "id", ACCOUNT_ID);
        return account;
    }

    private void prepareTokenIssue(AccountEntity account) {
        when(jwtProvider.createAccessToken(account)).thenReturn(ACCESS_TOKEN);
        when(jwtProvider.createRefreshToken(account)).thenReturn(REFRESH_TOKEN);
        when(jwtProvider.getAccessTokenExpiresInSeconds()).thenReturn(900L);
        when(jwtProvider.getRefreshTtl()).thenReturn(REFRESH_TTL);
    }
}
