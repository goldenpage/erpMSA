package com.oopsw.disposalsservice.disposal;
import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.*;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods=false)
public class StockClientConfiguration {
    static RestClient.Builder builder() {
        var factory=new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build());
        factory.setReadTimeout(Duration.ofSeconds(3));
        return RestClient.builder().requestFactory(factory);
    }
    // Eureka must contact its configured server directly, without service discovery.
    @Bean @Primary RestClient.Builder restClientBuilder() {return builder();}
    @Bean @LoadBalanced RestClient.Builder inventoryDiscoveryClient() {return builder();}
    @Bean StockClient stockClient(@Qualifier("inventoryDiscoveryClient") RestClient.Builder discovery,
        @Value("${app.inventory.base-url:http://FOODMATERIALSSERVICE}") String url,
        @Value("${app.inventory.discovery-enabled:true}") boolean useDiscovery,
        tools.jackson.databind.ObjectMapper mapper) {
        return new RestStockClient((useDiscovery?discovery:builder()).baseUrl(url).build(),mapper);
    }
}
