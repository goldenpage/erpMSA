package com.oopsw.accountservice.config;

import com.netflix.appinfo.ApplicationInfoManager;
import com.netflix.appinfo.InstanceInfo.InstanceStatus;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * 종료할 때 웹 서버를 멈추기 전에 Eureka에 DOWN을 알리고 {@code drain} 동안 요청을 계속 처리한다.
 *
 * <p>기본 종료 순서는 웹 서버 graceful shutdown(phase {@code Integer.MAX_VALUE - 1024})이 Eureka 등록 해제보다 먼저다.
 * 그 사이 Gateway는 레지스트리·로드밸런서 캐시에 남은 이 인스턴스로 계속 요청을 보내 실패한다
 * (docs/account-load-results.md 재배포 절). 이 Lifecycle은 그보다 높은 phase라 먼저 멈춘다.
 * drain은 Gateway의 레지스트리 갱신 주기 + 로드밸런서 캐시 TTL보다 길어야 한다.
 * 컨테이너 종료 유예(stop_grace_period)는 drain + graceful shutdown 시간보다 길어야 한다.
 */
@Component
public class DiscoveryDrainLifecycle implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(DiscoveryDrainLifecycle.class);
    static final int PHASE = Integer.MAX_VALUE - 512;

    private final ObjectProvider<ApplicationInfoManager> applicationInfoManager;
    private final Duration drain;
    private volatile boolean running;

    public DiscoveryDrainLifecycle(
        ObjectProvider<ApplicationInfoManager> applicationInfoManager,
        @Value("${app.shutdown.discovery-drain:15s}") Duration drain
    ) {
        if (drain.isNegative()) {
            throw new IllegalArgumentException("app.shutdown.discovery-drain must not be negative");
        }
        this.applicationInfoManager = applicationInfoManager;
        this.drain = drain;
    }

    @Override
    public void start() {
        running = true;
    }

    @Override
    public void stop() {
        running = false;
        ApplicationInfoManager manager = applicationInfoManager.getIfAvailable();
        if (manager == null || drain.isZero()) {
            return;
        }
        manager.setInstanceStatus(InstanceStatus.DOWN);
        log.info("Eureka에 DOWN을 알렸습니다. {}초 동안 처리 중·신규 요청을 계속 받은 뒤 종료합니다.", drain.toSeconds());
        try {
            Thread.sleep(drain.toMillis());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public boolean isRunning() {
        return running;
    }

    @Override
    public int getPhase() {
        return PHASE;
    }
}
