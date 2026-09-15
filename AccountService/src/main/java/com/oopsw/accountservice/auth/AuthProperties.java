package com.oopsw.accountservice.auth;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.auth")
public record AuthProperties(
    String issuer,
    String audience,
    String publicKeyDirectory,
    String signingKeyId,
    String privateKeyPath,
    Duration accessTtl,
    Duration refreshTtl,
    boolean secureCookie
) {
    public AuthProperties {
        if (issuer == null || issuer.isBlank()) {
            throw new IllegalArgumentException("JWT issuer가 필요합니다.");
        }

        if (audience == null || audience.isBlank()) {
            throw new IllegalArgumentException("JWT audience가 필요합니다.");
        }

        if (publicKeyDirectory == null || publicKeyDirectory.isBlank() ||
            signingKeyId == null || !signingKeyId.matches("[A-Za-z0-9_-]{1,64}") ||
            privateKeyPath == null || privateKeyPath.isBlank()) {
            throw new IllegalArgumentException("JWT 키 경로와 서명 키 ID가 필요합니다.");
        }

        if (accessTtl == null || accessTtl.isZero() || accessTtl.isNegative()) {
            throw new IllegalArgumentException("Access Token TTL이 올바르지 않습니다.");
        }

        if (refreshTtl == null || refreshTtl.isZero() || refreshTtl.isNegative()) {
            throw new IllegalArgumentException("Refresh Token TTL이 올바르지 않습니다.");
        }
    }
}