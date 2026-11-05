package com.oopsw.accountservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Duration;
import org.junit.jupiter.api.Test;

@org.junit.jupiter.api.Tag("unit")
class LoginAttemptLimiterTest {

    @Test
    void 반복_차단은_두_배씩_늘고_상한을_넘지_않는다() {
        Duration initial = Duration.ofMinutes(1);
        Duration max = Duration.ofMinutes(15);
        assertThat(LoginAttemptLimiter.lockDuration(1, initial, max)).isEqualTo(Duration.ofMinutes(1));
        assertThat(LoginAttemptLimiter.lockDuration(2, initial, max)).isEqualTo(Duration.ofMinutes(2));
        assertThat(LoginAttemptLimiter.lockDuration(4, initial, max)).isEqualTo(Duration.ofMinutes(8));
        assertThat(LoginAttemptLimiter.lockDuration(5, initial, max)).isEqualTo(Duration.ofMinutes(15));
        assertThat(LoginAttemptLimiter.lockDuration(500, initial, max)).isEqualTo(Duration.ofMinutes(15));
        assertThat(LoginAttemptLimiter.lockDuration(0, initial, max)).isEqualTo(Duration.ofMinutes(1));
    }

    @Test
    void 슬라이딩_구간은_경계에서_수가_한꺼번에_풀리지_않는다() {
        // 상한 30, 이전 구간을 다 쓴 주소: 새 구간 시작 직후에는 막히고, 이전 몫이 줄어든 만큼만 다시 허용된다.
        assertThat(LoginAttemptLimiter.slidingRetryAfter(30, 1, 0, 60, 30)).isPositive();
        assertThat(LoginAttemptLimiter.slidingRetryAfter(30, 1, 30, 60, 30)).isEqualTo(-1);   // 15 + 1 ≤ 30
        assertThat(LoginAttemptLimiter.slidingRetryAfter(30, 20, 30, 60, 30)).isPositive();   // 15 + 20 > 30
        assertThat(LoginAttemptLimiter.slidingRetryAfter(30, 20, 30, 60, 30)).isLessThanOrEqualTo(30);
        // 이전 기록이 없으면 현재 구간 상한까지 허용한다.
        assertThat(LoginAttemptLimiter.slidingRetryAfter(0, 30, 10, 60, 30)).isEqualTo(-1);
        assertThat(LoginAttemptLimiter.slidingRetryAfter(0, 31, 10, 60, 30)).isGreaterThanOrEqualTo(50);
    }

    @Test
    void 잘못된_설정은_시작하지_않는다() {
        assertThatThrownBy(() -> new LoginAttemptLimiter.Settings(true, 0, 10, Duration.ofMinutes(1), 5,
            Duration.ofMinutes(15), Duration.ofMinutes(1), Duration.ofMinutes(15))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new LoginAttemptLimiter.Settings(true, 30, 10, Duration.ofMinutes(1), 5,
            Duration.ofMinutes(15), Duration.ofMinutes(10), Duration.ofMinutes(1))).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void 클라이언트_주소는_신뢰_대역에서_온_헤더만_따른다() {
        ClientAddressResolver resolver = new ClientAddressResolver("10.0.0.0/8");
        var fromGateway = new org.springframework.mock.web.MockHttpServletRequest();
        fromGateway.setRemoteAddr("10.1.1.1");
        fromGateway.addHeader("X-Client-Address", "198.51.100.3");
        assertThat(resolver.resolve(fromGateway)).isEqualTo("198.51.100.3");

        var direct = new org.springframework.mock.web.MockHttpServletRequest();
        direct.setRemoteAddr("203.0.113.9");
        direct.addHeader("X-Client-Address", "198.51.100.3");
        assertThat(resolver.resolve(direct)).isEqualTo("203.0.113.9");

        var malformed = new org.springframework.mock.web.MockHttpServletRequest();
        malformed.setRemoteAddr("10.1.1.1");
        malformed.addHeader("X-Client-Address", "evil.example");
        assertThat(resolver.resolve(malformed)).isEqualTo("10.1.1.1");
    }
}
