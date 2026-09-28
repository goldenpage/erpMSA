package com.oopsw.foodmaterialsservice.support;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.test.context.DynamicPropertyRegistrar;
import org.testcontainers.mariadb.MariaDBContainer;

@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {
    @Bean
    @ServiceConnection
    MariaDBContainer mariaDBContainer(@Value("${test.inventory.legacy:false}") boolean legacy) {
        var database = isolatedDatabase()
            .withDatabaseName("item_service_test")
            .withUsername("item").withPassword("test-password");
        if (legacy) {
            database.start();
            try {
                LegacyMigrationFixture.prepare(database, "catalog");
            } catch (RuntimeException exception) {
                database.stop();
                throw exception;
            }
        }
        return database;
    }

    @Bean(defaultCandidate = false)
    MariaDBContainer inventoryDatabase(@Value("${test.inventory.legacy:false}") boolean legacy) {
        var database = isolatedDatabase()
            .withDatabaseName("inventory_service_test")
            .withUsername("inventory").withPassword("test-password");
        database.start();
        if (!legacy) {
            return database;
        }
        try {
            LegacyMigrationFixture.prepare(database, "inventory");
        } catch (RuntimeException exception) {
            database.stop();
            throw exception;
        }
        return database;
    }

    private static MariaDBContainer isolatedDatabase() {
        return new MariaDBContainer("mariadb:10.11")
            .withLabel("erpmsa.verification.run", System.getenv().getOrDefault("ERPMSA_VERIFICATION_RUN_ID", "standalone"))
            .withTmpFs(java.util.Map.of("/var/lib/mysql", "rw")).withReuse(false);
    }

    @Bean
    DynamicPropertyRegistrar inventoryProperties(@Qualifier("inventoryDatabase") MariaDBContainer database) {
        return registry -> {
            registry.add("app.inventory.datasource.url", database::getJdbcUrl);
            registry.add("app.inventory.datasource.username", database::getUsername);
            registry.add("app.inventory.datasource.password", database::getPassword);
        };
    }
}
