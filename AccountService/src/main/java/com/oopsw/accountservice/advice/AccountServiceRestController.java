package com.oopsw.accountservice.advice;

import com.oopsw.accountservice.advice.dto.LoginRequest;
import com.oopsw.accountservice.advice.dto.RegisterRequest;

import com.oopsw.accountservice.auth.AuthPrincipal;
import com.oopsw.accountservice.auth.AuthProperties;
import com.oopsw.accountservice.service.AccountService;
import jakarta.validation.Valid;
import java.time.Duration;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/account/auth")
@RequiredArgsConstructor
public class AccountServiceRestController {

    private static final String REFRESH_COOKIE = "refreshToken";

    private final AccountService accountService;
    private final AuthProperties properties;

    @PostMapping("/register")
    public ResponseEntity<AccountService.RegisterResponse> register(
        @Valid @RequestBody RegisterRequest request
    ) {
        return ResponseEntity.status(HttpStatus.CREATED)
            .body(accountService.register(request));
    }

    @PostMapping("/login")
    public ResponseEntity<AccessTokenResponse> login(
        @Valid @RequestBody LoginRequest request
    ) {
        return tokenResponse(accountService.login(request));
    }

    @PostMapping("/refresh")
    public ResponseEntity<AccessTokenResponse> refresh(
        @CookieValue(
            name = REFRESH_COOKIE,
            required = false
        ) String refreshToken
    ) {
        return tokenResponse(accountService.refresh(refreshToken));
    }

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(
        @CookieValue(
            name = REFRESH_COOKIE,
            required = false
        ) String refreshToken
    ) {
        accountService.logout(refreshToken);

        return ResponseEntity.noContent()
            .header(
                HttpHeaders.SET_COOKIE,
                deleteRefreshCookie().toString()
            )
            .build();
    }

    @GetMapping("/me")
    public AuthPrincipal me(
        @AuthenticationPrincipal AuthPrincipal principal
    ) {
        return principal;
    }

    private ResponseEntity<AccessTokenResponse> tokenResponse(
        AccountService.IssuedTokens tokens
    ) {
        HttpHeaders headers = new HttpHeaders();

        headers.setBearerAuth(tokens.accessToken());
        headers.add(
            HttpHeaders.SET_COOKIE,
            createRefreshCookie(tokens.refreshToken()).toString()
        );

        return ResponseEntity.ok()
            .headers(headers)
            .body(new AccessTokenResponse(
                "Bearer",
                tokens.accessToken(),
                tokens.accessTokenExpiresIn()
            ));
    }

    private ResponseCookie createRefreshCookie(String refreshToken) {
        return ResponseCookie.from(REFRESH_COOKIE, refreshToken)
            .httpOnly(true)
            .secure(properties.secureCookie())
            .sameSite("Strict")
            .path("/account/auth")
            .maxAge(properties.refreshTtl())
            .build();
    }

    private ResponseCookie deleteRefreshCookie() {
        return ResponseCookie.from(REFRESH_COOKIE, "")
            .httpOnly(true)
            .secure(properties.secureCookie())
            .sameSite("Strict")
            .path("/account/auth")
            .maxAge(Duration.ZERO)
            .build();
    }

    public record AccessTokenResponse(
        String tokenType,
        String accessToken,
        long expiresIn
    ) {
    }
}