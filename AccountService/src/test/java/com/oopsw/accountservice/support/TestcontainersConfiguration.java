package com.oopsw.accountservice.support;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.kafka.KafkaContainer;
import org.testcontainers.mariadb.MariaDBContainer;

@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {

    @Bean
    @ServiceConnection
    MariaDBContainer mariaDBContainer() {
        return new MariaDBContainer("mariadb:10.11")
            .withLabel("erpmsa.verification.run", runId())
            .withTmpFs(java.util.Map.of("/var/lib/mysql", "rw"))
            .withReuse(false)
            .withDatabaseName("account_service_test")
            .withUsername("account")
            .withPassword("test-password");
    }

    @Bean
    @ServiceConnection(name = "redis")
    GenericContainer<?> redisContainer() {
        return new GenericContainer<>("redis:8-alpine")
            .withLabel("erpmsa.verification.run", runId())
            .withTmpFs(java.util.Map.of("/data", "rw"))
            .withReuse(false)
            .withExposedPorts(6379);
    }

    @Bean
    @ServiceConnection
    KafkaContainer kafkaContainer() {
        return new KafkaContainer("apache/kafka:4.3.1")
            .withLabel("erpmsa.verification.run", runId())
            .withEnv("KAFKA_LOG_DIRS", "/tmp/kraft-combined-logs")
            .withTmpFs(java.util.Map.of("/tmp/kraft-combined-logs", "rw,mode=1777",
                "/etc/kafka/secrets", "rw,mode=1777", "/mnt/shared/config", "rw,mode=1777",
                "/var/lib/kafka/data", "rw,mode=1777"))
            .withReuse(false);
    }

    private static String runId() {
        return System.getenv().getOrDefault("ERPMSA_VERIFICATION_RUN_ID", "standalone");
    }
}
