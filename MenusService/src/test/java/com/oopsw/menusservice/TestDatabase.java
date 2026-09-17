package com.oopsw.menusservice;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.mariadb.MariaDBContainer;
@TestConfiguration(proxyBeanMethods=false)
public class TestDatabase {
    @Bean @ServiceConnection MariaDBContainer database() {
        return new MariaDBContainer("mariadb:10.11").withDatabaseName("menus_test").withUsername("test").withPassword("test-password");
    }
}
