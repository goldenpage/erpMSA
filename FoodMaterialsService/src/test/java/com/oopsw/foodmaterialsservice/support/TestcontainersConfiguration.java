package com.oopsw.foodmaterialsservice.support;

import org.flywaydb.core.Flyway;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.test.context.DynamicPropertyRegistrar;
import org.testcontainers.mariadb.MariaDBContainer;

@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {
    @Bean
    @ServiceConnection
    MariaDBContainer mariaDBContainer() {
        return new MariaDBContainer("mariadb:10.11")
            .withDatabaseName("item_service_test")
            .withUsername("item").withPassword("test-password");
    }

    @Bean(defaultCandidate = false)
    MariaDBContainer inventoryDatabase() {
        var database = new MariaDBContainer("mariadb:10.11")
            .withDatabaseName("inventory_service_test")
            .withUsername("inventory").withPassword("test-password");
        database.start();
        // Model the pre-existing service's schema/history and data before the new app starts.
        Flyway.configure().dataSource(database.getJdbcUrl(), database.getUsername(), database.getPassword())
            .locations("classpath:db/inventory-migration").load().migrate();
        try (var connection = java.sql.DriverManager.getConnection(
                database.getJdbcUrl(), database.getUsername(), database.getPassword());
             var statement = connection.createStatement()) {
            statement.executeUpdate("INSERT INTO inventory (id,account_id,item_id,on_hand_quantity,version,created_at,updated_at) VALUES (77,101,777,42,3,NOW(),NOW())");
            statement.executeUpdate("INSERT INTO stock_movement (id,inventory_id,account_id,item_id,request_id,movement_type,quantity_delta,quantity_before,quantity_after,reason,created_at) VALUES (88,77,101,777,'INITIAL-77','INITIAL',42,0,42,'legacy',NOW())");
        } catch (java.sql.SQLException exception) {
            database.stop();
            throw new IllegalStateException(exception);
        }
        return database;
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
