package com.oopsw.accountservice.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class RefreshTokenStore {

    private static final String KEY_PREFIX = "account:refresh:";

    private final StringRedisTemplate redisTemplate;

    /**
     * Refresh Token 원문 대신 SHA-256 해시를 Redis Key로 저장한다.
     *
     * key   : account:refresh:{tokenHash}
     * value : accountId
     * TTL   : Refresh Token 만료시간
     */
    public void save(
        String refreshToken,
        Long accountId,
        Duration ttl
    ) {
        redisTemplate.opsForValue().set(
            createKey(refreshToken),
            accountId.toString(),
            ttl
        );
    }

    /**
     * GETDEL을 사용해서 Refresh Token을 한 번만 사용할 수 있게 한다.
     */
    public Long consume(String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            return null;
        }

        String accountId = redisTemplate.opsForValue()
            .getAndDelete(createKey(refreshToken));

        if (accountId == null) {
            return null;
        }

        try {
            return Long.valueOf(accountId);
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    /**
     * 로그아웃할 때 Refresh Token을 Redis에서 제거한다.
     */
    public void revoke(String refreshToken) {
        if (refreshToken == null || refreshToken.isBlank()) {
            return;
        }

        redisTemplate.delete(createKey(refreshToken));
    }

    private String createKey(String refreshToken) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");

            byte[] tokenHash = digest.digest(
                refreshToken.getBytes(StandardCharsets.UTF_8)
            );

            return KEY_PREFIX + HexFormat.of().formatHex(tokenHash);

        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(
                "SHA-256 알고리즘을 사용할 수 없습니다.",
                exception
            );
        }
    }
}