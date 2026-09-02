package com.oopsw.inventoryservice.support;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.mariadb.MariaDBContainer;

@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {

    @Bean
    @ServiceConnection
    MariaDBContainer mariaDBContainer() {
        return new MariaDBContainer("mariadb:10.11")
            .withDatabaseName("inventory_service_test")
            .withUsername("inventory")
            .withPassword("test-password");
    }
}
