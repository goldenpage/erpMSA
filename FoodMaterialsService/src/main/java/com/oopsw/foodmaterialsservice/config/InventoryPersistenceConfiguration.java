package com.oopsw.foodmaterialsservice.config;

import com.oopsw.foodmaterialsservice.inventory.domain.InventoryEntity;
import com.oopsw.foodmaterialsservice.inventory.domain.InventoryRepository;
import com.zaxxer.hikari.HikariDataSource;
import jakarta.persistence.EntityManagerFactory;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.jdbc.autoconfigure.DataSourceProperties;
import org.springframework.boot.jpa.EntityManagerFactoryBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.DependsOn;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;

@Configuration(proxyBeanMethods = false)
@EnableJpaRepositories(basePackageClasses = InventoryRepository.class,
    entityManagerFactoryRef = "inventoryEntityManagerFactory",
    transactionManagerRef = "inventoryTransactionManager")
public class InventoryPersistenceConfiguration {
    @Bean(defaultCandidate = false)
    @ConfigurationProperties("app.inventory.datasource")
    DataSourceProperties inventoryDataSourceProperties() {
        return new DataSourceProperties();
    }

    @Bean(defaultCandidate = false)
    @ConfigurationProperties("app.inventory.datasource.hikari")
    HikariDataSource inventoryDataSource(
        @Qualifier("inventoryDataSourceProperties") DataSourceProperties properties
    ) {
        return properties.initializeDataSourceBuilder().type(HikariDataSource.class).build();
    }

    @Bean(defaultCandidate = false, initMethod = "migrate")
    Flyway inventoryFlyway(
        @Qualifier("inventoryDataSource") DataSource dataSource,
        @Value("${app.inventory.flyway.baseline-on-migrate:false}") boolean baseline
    ) {
        // Separate history and unchanged V1 preserve the former Inventory database.
        return Flyway.configure().dataSource(dataSource)
            .locations("classpath:db/inventory-migration")
            .baselineOnMigrate(baseline).cleanDisabled(true).load();
    }

    @Bean(defaultCandidate = false)
    @DependsOn("inventoryFlyway")
    LocalContainerEntityManagerFactoryBean inventoryEntityManagerFactory(
        EntityManagerFactoryBuilder builder,
        @Qualifier("inventoryDataSource") DataSource dataSource
    ) {
        return builder.dataSource(dataSource).packages(InventoryEntity.class)
            .persistenceUnit("inventory").build();
    }

    @Bean(defaultCandidate = false)
    JpaTransactionManager inventoryTransactionManager(
        @Qualifier("inventoryEntityManagerFactory") EntityManagerFactory factory
    ) {
        return new JpaTransactionManager(factory);
    }
}
