package com.oopsw.inventoryservice.config;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

class RestClientConfigTest {

    @Test
    void unqualifiedRestClientBuilderUsesPlainPrimaryBean() {
        try (
            AnnotationConfigApplicationContext context =
                new AnnotationConfigApplicationContext(
                    RestClientConfig.class,
                    LoadBalancedClientTestConfig.class
                )
        ) {
            RestClient.Builder primaryBuilder = context.getBean(
                RestClient.Builder.class
            );

            assertThat(primaryBuilder)
                .isSameAs(context.getBean("restClientBuilder"));
            assertThat(context.getBeanNamesForType(RestClient.Builder.class))
                .containsExactlyInAnyOrder(
                    "restClientBuilder",
                    "loadBalancedRestClientBuilder"
                );
            assertThat(
                context.getBean(LoadBalancedBuilderHolder.class).builder()
            ).isSameAs(context.getBean("loadBalancedRestClientBuilder"));
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class LoadBalancedClientTestConfig {

        @Bean
        LoadBalancedBuilderHolder loadBalancedBuilderHolder(
            @LoadBalanced RestClient.Builder builder
        ) {
            return new LoadBalancedBuilderHolder(builder);
        }
    }

    record LoadBalancedBuilderHolder(RestClient.Builder builder) {}
}
