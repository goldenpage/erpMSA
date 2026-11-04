package com.oopsw.accountservice.auth;

import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiException;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * BCrypt 계산(로그인 검증·가입 해시)의 동시 실행 수를 제한한다.
 *
 * <p>BCrypt는 CPU를 오래 쓰므로 처리 한계를 넘는 요청을 모두 받아들이면 대기열이 길어져
 * 모든 요청이 클라이언트 제한 시간을 넘기고 성공 처리량이 0으로 무너진다(docs/account-load-results.md 발견 2).
 * 허가를 {@code max-wait} 안에 얻지 못한 요청은 계산하지 않고 503 AUTH_BUSY로 거절한다.
 */
@Component
public class PasswordHashGate {

    private final Semaphore permits;
    private final long maxWaitNanos;
    private final Counter rejected;

    public PasswordHashGate(
        @Value("${app.auth.password-hash.max-concurrent:0}") int maxConcurrent,
        @Value("${app.auth.password-hash.max-wait:2s}") Duration maxWait,
        MeterRegistry registry
    ) {
        int size = maxConcurrent > 0 ? maxConcurrent : defaultPermits(Runtime.getRuntime().availableProcessors());
        if (maxWait.isNegative()) {
            throw new IllegalArgumentException("app.auth.password-hash.max-wait must not be negative");
        }
        this.permits = new Semaphore(size, true);
        this.maxWaitNanos = maxWait.toNanos();
        Gauge.builder("account.password.hash.in.use", permits, p -> size - p.availablePermits())
            .description("실행 중인 BCrypt 계산 수").register(registry);
        Gauge.builder("account.password.hash.waiting", permits, Semaphore::getQueueLength)
            .description("BCrypt 허가를 기다리는 요청 수").register(registry);
        Gauge.builder("account.password.hash.permits", () -> size).register(registry);
        this.rejected = Counter.builder("account.password.hash.rejected")
            .description("대기 한도 안에 허가를 얻지 못해 거절한 요청 수").register(registry);
    }

    /** CPU 바운드 계산이므로 코어 수보다 많이 동시에 돌려도 처리량은 늘지 않는다. 최소 2개. */
    static int defaultPermits(int processors) {
        return Math.max(2, processors);
    }

    public <T> T run(Supplier<T> work) {
        boolean acquired;
        try {
            acquired = permits.tryAcquire(maxWaitNanos, TimeUnit.NANOSECONDS);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ApiException(ApiErrorCode.AUTH_BUSY);
        }
        if (!acquired) {
            rejected.increment();
            throw new ApiException(ApiErrorCode.AUTH_BUSY);
        }
        try {
            return work.get();
        } finally {
            permits.release();
        }
    }
}
