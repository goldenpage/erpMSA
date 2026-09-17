package com.oopsw.foodmaterialsservice.config;

import com.oopsw.foodmaterialsservice.domain.FoodMaterialEntity;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialRepository;
import org.springframework.boot.persistence.autoconfigure.EntityScan;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

@Configuration(proxyBeanMethods = false)
@EntityScan(basePackageClasses = FoodMaterialEntity.class)
@EnableJpaRepositories(basePackageClasses = FoodMaterialRepository.class)
public class CatalogPersistenceConfiguration {
}
