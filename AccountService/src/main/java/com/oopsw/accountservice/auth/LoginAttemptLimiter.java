package com.oopsw.accountservice.auth;

import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiException;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.util.HexFormat;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 로그인·회원가입 시도 제한. 모든 검사는 BCrypt보다 먼저 실행되어 막힌 시도는 CPU를 쓰지 않는다.
 *
 * <ul>
 *   <li>IP 기준: 슬라이딩 구간(기본 1분) 근사로 로그인 {@code login-per-ip}, 가입 {@code register-per-ip}회까지.</li>
 *   <li>계정 기준: 입력한 이메일(가입 여부와 무관)로 {@code failure-window} 안에 {@code failures-before-lock}회 실패하면
 *       잠시 막는다. 막힌 시간은 {@code lock-initial}부터 반복될 때마다 두 배, 최대 {@code lock-max}. 성공하면 초기화한다.</li>
 * </ul>
 * 영구 잠금은 하지 않는다. 이메일·IP 원문 대신 SHA-256 해시를 Redis 키로 쓴다.
 */
@Component
public class LoginAttemptLimiter {

    private static final String PREFIX = "account:rl:";

    private final StringRedisTemplate redis;
    private final Clock clock;
    private final Settings settings;
    private final Counter loginLimitedByIp;
    private final Counter loginLimitedByAccount;
    private final Counter registerLimitedByIp;
    private final Counter accountLocks;

    public record Settings(boolean enabled, int loginPerIp, int registerPerIp, Duration ipWindow,
                           int failuresBeforeLock, Duration failureWindow, Duration lockInitial, Duration lockMax) {
        public Settings {
            if (loginPerIp < 1 || registerPerIp < 1 || failuresBeforeLock < 1 || ipWindow.toSeconds() < 1
                || failureWindow.toSeconds() < 1 || lockInitial.toSeconds() < 1 || lockMax.compareTo(lockInitial) < 0) {
                throw new IllegalArgumentException("Invalid app.auth.rate-limit settings");
            }
        }
    }

    @Autowired
    public LoginAttemptLimiter(
        StringRedisTemplate redis,
        MeterRegistry registry,
        @Value("${app.auth.rate-limit.enabled:true}") boolean enabled,
        @Value("${app.auth.rate-limit.login-per-ip:30}") int loginPerIp,
        @Value("${app.auth.rate-limit.register-per-ip:10}") int registerPerIp,
        @Value("${app.auth.rate-limit.ip-window:1m}") Duration ipWindow,
        @Value("${app.auth.rate-limit.failures-before-lock:5}") int failuresBeforeLock,
        @Value("${app.auth.rate-limit.failure-window:15m}") Duration failureWindow,
        @Value("${app.auth.rate-limit.lock-initial:1m}") Duration lockInitial,
        @Value("${app.auth.rate-limit.lock-max:15m}") Duration lockMax
    ) {
        this(redis, registry, Clock.systemUTC(), new Settings(enabled, loginPerIp, registerPerIp, ipWindow,
            failuresBeforeLock, failureWindow, lockInitial, lockMax));
    }

    LoginAttemptLimiter(StringRedisTemplate redis, MeterRegistry registry, Clock clock, Settings settings) {
        this.redis = redis;
        this.clock = clock;
        this.settings = settings;
        this.loginLimitedByIp = Counter.builder("account.login.rate.limited").tag("reason", "ip").register(registry);
        this.loginLimitedByAccount = Counter.builder("account.login.rate.limited").tag("reason", "account").register(registry);
        this.registerLimitedByIp = Counter.builder("account.register.rate.limited").tag("reason", "ip").register(registry);
        this.accountLocks = Counter.builder("account.login.locks").description("실패 누적으로 계정 기준 차단을 건 횟수").register(registry);
    }

    /** 반복 차단 시간: lock-initial × 2^(n-1), 최대 lock-max. */
    static Duration lockDuration(int lockNumber, Duration initial, Duration max) {
        int exponent = Math.min(Math.max(lockNumber, 1) - 1, 20);
        Duration value = initial.multipliedBy(1L << exponent);
        return value.compareTo(max) > 0 ? max : value;
    }

    public void checkLogin(String clientAddress, String normalizedEmail) {
        if (!settings.enabled()) {
            return;
        }
        Long ipRetry = overIpLimit("login", clientAddress, settings.loginPerIp());
        if (ipRetry != null) {
            loginLimitedByIp.increment();
            throw new ApiException(ApiErrorCode.LOGIN_RATE_LIMITED, ipRetry);
        }
        Long lockTtl = redis.getExpire(PREFIX + "lock:" + hash(normalizedEmail));
        if (lockTtl != null && lockTtl > 0) {
            loginLimitedByAccount.increment();
            throw new ApiException(ApiErrorCode.LOGIN_RATE_LIMITED, lockTtl);
        }
    }

    public void checkRegister(String clientAddress) {
        if (!settings.enabled()) {
            return;
        }
        Long retry = overIpLimit("register", clientAddress, settings.registerPerIp());
        if (retry != null) {
            registerLimitedByIp.increment();
            throw new ApiException(ApiErrorCode.REGISTER_RATE_LIMITED, retry);
        }
    }

    public void recordFailure(String normalizedEmail) {
        if (!settings.enabled()) {
            return;
        }
        String key = hash(normalizedEmail);
        String failKey = PREFIX + "fail:" + key;
        Long failures = redis.opsForValue().increment(failKey);
        if (failures != null && failures == 1) {
            redis.expire(failKey, settings.failureWindow());
        }
        if (failures != null && failures >= settings.failuresBeforeLock()) {
            String countKey = PREFIX + "locks:" + key;
            Long locks = redis.opsForValue().increment(countKey);
            redis.expire(countKey, Duration.ofDays(1));
            Duration lock = lockDuration(locks == null ? 1 : locks.intValue(), settings.lockInitial(), settings.lockMax());
            redis.opsForValue().set(PREFIX + "lock:" + key, "1", lock);
            redis.delete(failKey);
            accountLocks.increment();
        }
    }

    public void recordSuccess(String normalizedEmail) {
        if (!settings.enabled()) {
            return;
        }
        String key = hash(normalizedEmail);
        redis.delete(java.util.List.of(PREFIX + "fail:" + key, PREFIX + "locks:" + key));
    }

    /**
     * 초과했으면 다시 시도할 수 있을 때까지의 초, 아니면 null.
     *
     * <p>슬라이딩 구간 근사: 추정치 = 이전 구간 수 × (구간에서 남은 비율) + 현재 구간 수.
     * 고정 구간은 경계마다 수가 0이 되어 그 순간 상한만큼 몰리는 문제가 있었다(재측정에서 경계마다 p95 급등).
     * 거절된 시도도 센다. 계속 두드리는 주소는 풀리지 않는다.
     */
    private Long overIpLimit(String action, String clientAddress, int limit) {
        long windowSeconds = settings.ipWindow().toSeconds();
        long now = clock.instant().getEpochSecond();
        long window = now / windowSeconds;
        String base = PREFIX + action + ":ip:" + hash(clientAddress) + ":";
        Long current = redis.opsForValue().increment(base + window);
        if (current != null && current == 1) {
            redis.expire(base + window, Duration.ofSeconds(windowSeconds * 2));
        }
        String previousValue = redis.opsForValue().get(base + (window - 1));
        long previous = previousValue == null ? 0 : Long.parseLong(previousValue);
        long retry = slidingRetryAfter(previous, current == null ? 0 : current, now % windowSeconds, windowSeconds, limit);
        return retry < 0 ? null : retry;
    }

    /** 상한 안이면 -1, 넘으면 추정치가 상한 이하로 내려갈 때까지의 초(최소 1). */
    static long slidingRetryAfter(long previous, long current, long elapsed, long window, int limit) {
        double remaining = (double) (window - elapsed) / window;
        double estimate = previous * remaining + current;
        if (estimate <= limit) {
            return -1;
        }
        long toNextWindow = window - elapsed;
        if (current > limit || previous == 0) {
            // 현재 구간만으로 넘었다. 다음 구간에서는 이번 수가 이전 수가 되므로 그만큼 더 기다린다.
            double nextFraction = Math.max(0, 1 - (double) limit / Math.max(1, current));
            return Math.max(1, toNextWindow + (long) Math.ceil(window * nextFraction));
        }
        // 이전 구간의 몫이 줄어들어 추정치가 상한에 닿는 시점.
        double secondsUntilFit = (estimate - limit) * window / previous;
        return Math.max(1, Math.min(toNextWindow, (long) Math.ceil(secondsUntilFit)));
    }

    private static String hash(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest(String.valueOf(value).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest, 0, 16);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 알고리즘을 사용할 수 없습니다.", exception);
        }
    }
}
