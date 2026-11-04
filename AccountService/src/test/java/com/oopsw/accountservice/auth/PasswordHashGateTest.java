package com.oopsw.accountservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiException;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

class PasswordHashGateTest {

    @Test
    void 기본_허가_수는_CPU_수이며_최소_2개다() {
        assertThat(PasswordHashGate.defaultPermits(1)).isEqualTo(2);
        assertThat(PasswordHashGate.defaultPermits(8)).isEqualTo(8);
    }

    @Test
    void 허가를_모두_쓰면_대기_한도_뒤_계산하지_않고_AUTH_BUSY로_거절한다() throws Exception {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        PasswordHashGate gate = new PasswordHashGate(1, Duration.ofMillis(100), registry);
        CountDownLatch running = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<Boolean> holder = executor.submit(() -> gate.run(() -> {
                running.countDown();
                try {
                    return release.await(5, TimeUnit.SECONDS);
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    return false;
                }
            }));
            assertThat(running.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(registry.get("account.password.hash.in.use").gauge().value()).isEqualTo(1.0);

            boolean[] computed = {false};
            long started = System.nanoTime();
            assertThatThrownBy(() -> gate.run(() -> computed[0] = true))
                .isInstanceOf(ApiException.class)
                .extracting(e -> ((ApiException) e).errorCode()).isEqualTo(ApiErrorCode.AUTH_BUSY);
            assertThat(Duration.ofNanos(System.nanoTime() - started)).isGreaterThanOrEqualTo(Duration.ofMillis(90));
            assertThat(computed[0]).isFalse();
            assertThat(registry.get("account.password.hash.rejected").counter().count()).isEqualTo(1.0);

            release.countDown();
            assertThat(holder.get(5, TimeUnit.SECONDS)).isTrue();
        } finally {
            release.countDown();
            executor.shutdownNow();
        }
        assertThat(gate.run(() -> "ok")).isEqualTo("ok");
    }

    @Test
    void 계산이_실패해도_허가를_반환한다() {
        PasswordHashGate gate = new PasswordHashGate(1, Duration.ZERO, new SimpleMeterRegistry());
        for (int i = 0; i < 3; i++) {
            assertThatThrownBy(() -> gate.run(() -> {
                throw new IllegalStateException("hash failure");
            })).isInstanceOf(IllegalStateException.class);
        }
        assertThat(gate.run(() -> 1)).isEqualTo(1);
    }
}
