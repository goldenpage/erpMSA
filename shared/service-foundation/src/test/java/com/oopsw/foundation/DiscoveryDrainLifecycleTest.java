package com.oopsw.foundation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.netflix.appinfo.ApplicationInfoManager;
import com.netflix.appinfo.InstanceInfo.InstanceStatus;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;

class DiscoveryDrainLifecycleTest {

    private static DiscoveryDrainLifecycle lifecycle(ApplicationInfoManager manager, Duration drain) {
        DefaultListableBeanFactory factory = new DefaultListableBeanFactory();
        if (manager != null) {
            factory.registerSingleton("applicationInfoManager", manager);
        }
        return new DiscoveryDrainLifecycle(factory.getBeanProvider(ApplicationInfoManager.class), drain);
    }

    @Test
    void 웹_서버_graceful_shutdown보다_먼저_멈춘다() {
        // 높은 phase가 먼저 멈춘다. WebServerGracefulShutdownLifecycle은 Integer.MAX_VALUE - 1024.
        assertThat(lifecycle(null, Duration.ofSeconds(15)).getPhase()).isGreaterThan(Integer.MAX_VALUE - 1024);
    }

    @Test
    void 종료하면_DOWN을_알리고_drain_시간만큼_기다린다() {
        ApplicationInfoManager manager = mock(ApplicationInfoManager.class);
        DiscoveryDrainLifecycle lifecycle = lifecycle(manager, Duration.ofMillis(300));
        lifecycle.start();

        long started = System.nanoTime();
        lifecycle.stop();

        verify(manager).setInstanceStatus(InstanceStatus.DOWN);
        assertThat(Duration.ofNanos(System.nanoTime() - started)).isGreaterThanOrEqualTo(Duration.ofMillis(280));
        assertThat(lifecycle.isRunning()).isFalse();
    }

    @Test
    void Eureka가_없거나_drain이_0이면_바로_끝난다() {
        long started = System.nanoTime();
        lifecycle(null, Duration.ofSeconds(5)).stop();
        assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofSeconds(1));

        ApplicationInfoManager manager = mock(ApplicationInfoManager.class);
        lifecycle(manager, Duration.ZERO).stop();
        verifyNoInteractions(manager);
    }

    @Test
    void 음수_drain은_거부한다() {
        assertThatThrownBy(() -> lifecycle(null, Duration.ofSeconds(-1)))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
