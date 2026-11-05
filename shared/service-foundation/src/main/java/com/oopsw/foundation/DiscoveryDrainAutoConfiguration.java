package com.oopsw.foundation;

import com.netflix.appinfo.ApplicationInfoManager;
import java.time.Duration;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;

/**
 * 이 모듈을 쓰는 서비스에 {@link DiscoveryDrainLifecycle}을 등록한다.
 *
 * <p>서비스마다 {@code @Import}를 빠뜨리지 않도록 자동 구성으로 둔다
 * (META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports).
 * Eureka 클라이언트가 꺼져 있으면 ApplicationInfoManager가 없어 종료 시 바로 끝난다.
 */
@AutoConfiguration
@ConditionalOnClass(ApplicationInfoManager.class)
public class DiscoveryDrainAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    DiscoveryDrainLifecycle discoveryDrainLifecycle(
        ObjectProvider<ApplicationInfoManager> applicationInfoManager,
        @Value("${app.shutdown.discovery-drain:15s}") Duration drain
    ) {
        return new DiscoveryDrainLifecycle(applicationInfoManager, drain);
    }
}
