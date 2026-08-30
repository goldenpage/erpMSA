package com.oopsw.accountservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Duration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

@ExtendWith(MockitoExtension.class)
class RefreshTokenStoreTest {

    private static final String REFRESH_TOKEN = "raw-refresh-token";

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ValueOperations<String, String> valueOperations;

    private RefreshTokenStore refreshTokenStore;

    @BeforeEach
    void setUp() {
        refreshTokenStore = new RefreshTokenStore(redisTemplate);
    }

    @Test
    void RefreshToken_원문이_아닌_해시를_저장한다() {
        Duration ttl = Duration.ofDays(14);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        refreshTokenStore.save(REFRESH_TOKEN, 1L, ttl);

        ArgumentCaptor<String> keyCaptor =
            ArgumentCaptor.forClass(String.class);
        verify(valueOperations).set(keyCaptor.capture(), eq("1"), eq(ttl));
        assertHashedKey(keyCaptor.getValue());
    }

    @Test
    void consume은_토큰을_조회하고_동시에_삭제한다() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.getAndDelete(anyString())).thenReturn("1");

        Long accountId = refreshTokenStore.consume(REFRESH_TOKEN);

        assertThat(accountId).isEqualTo(1L);
        ArgumentCaptor<String> keyCaptor =
            ArgumentCaptor.forClass(String.class);
        verify(valueOperations).getAndDelete(keyCaptor.capture());
        assertHashedKey(keyCaptor.getValue());
    }

    @Test
    void 이미_소비한_RefreshToken은_null을_반환한다() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.getAndDelete(anyString())).thenReturn(null);

        assertThat(refreshTokenStore.consume(REFRESH_TOKEN)).isNull();
    }

    @Test
    void Redis의_accountId가_숫자가_아니면_null을_반환한다() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.getAndDelete(anyString()))
            .thenReturn("not-number");

        assertThat(refreshTokenStore.consume(REFRESH_TOKEN)).isNull();
    }

    @Test
    void 로그아웃하면_RefreshToken을_삭제한다() {
        refreshTokenStore.revoke(REFRESH_TOKEN);

        ArgumentCaptor<String> keyCaptor =
            ArgumentCaptor.forClass(String.class);
        verify(redisTemplate).delete(keyCaptor.capture());
        assertHashedKey(keyCaptor.getValue());
    }

    @Test
    void 빈_RefreshToken은_Redis에_접근하지_않는다() {
        assertThat(refreshTokenStore.consume(" ")).isNull();
        refreshTokenStore.revoke(" ");

        verify(redisTemplate, never()).opsForValue();
        verify(redisTemplate, never()).delete(anyString());
    }

    private void assertHashedKey(String key) {
        assertThat(key).startsWith("account:refresh:");
        assertThat(key).doesNotContain(REFRESH_TOKEN);
    }
}
