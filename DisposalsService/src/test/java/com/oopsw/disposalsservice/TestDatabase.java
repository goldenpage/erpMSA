package com.oopsw.disposalsservice;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.mariadb.MariaDBContainer;
@TestConfiguration(proxyBeanMethods=false)
public class TestDatabase {
    @Bean @ServiceConnection MariaDBContainer database() {
        return new MariaDBContainer("mariadb:10.11")
            .withLabel("erpmsa.verification.run", System.getenv().getOrDefault("ERPMSA_VERIFICATION_RUN_ID", "standalone"))
            .withTmpFs(java.util.Map.of("/var/lib/mysql", "rw")).withReuse(false)
            .withDatabaseName("disposals_test").withUsername("test").withPassword("test-password");
    }
}
