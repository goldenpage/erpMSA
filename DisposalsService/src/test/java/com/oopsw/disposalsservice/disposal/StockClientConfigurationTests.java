package com.oopsw.disposalsservice.disposal;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.client.loadbalancer.LoadBalancerRestClientBuilderBeanPostProcessor;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

class StockClientConfigurationTests {
    @Test
    void infrastructureRequestsBypassDiscoveryWhileInventoryRequestsUseIt() throws Exception {
        var discoveryCalls = new AtomicInteger();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/eureka/apps", exchange -> {
            byte[] body = "registered".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try (var context = new AnnotationConfigApplicationContext()) {
            ClientHttpRequestInterceptor discovery = (request, body, execution) -> {
                discoveryCalls.incrementAndGet();
                return execution.execute(request, body);
            };
            context.registerBean(ClientHttpRequestInterceptor.class, () -> discovery);
            context.registerBean("discoveryPostProcessor",
                LoadBalancerRestClientBuilderBeanPostProcessor.class,
                () -> new LoadBalancerRestClientBuilderBeanPostProcessor<>(
                    context.getBeanProvider(ClientHttpRequestInterceptor.class), context));
            context.registerBean(ObjectMapper.class, () -> new ObjectMapper());
            context.register(StockClientConfiguration.class);
            context.refresh();

            String url = "http://127.0.0.1:" + server.getAddress().getPort() + "/eureka/apps";
            assertThat(context.getBean(RestClient.Builder.class).build()
                .get().uri(url).retrieve().body(String.class)).isEqualTo("registered");
            assertThat(discoveryCalls).hasValue(0);

            assertThat(context.getBean("inventoryDiscoveryClient", RestClient.Builder.class).build()
                .get().uri(url).retrieve().body(String.class)).isEqualTo("registered");
            assertThat(discoveryCalls).hasValue(1);
        } finally {
            server.stop(0);
        }
    }
}
