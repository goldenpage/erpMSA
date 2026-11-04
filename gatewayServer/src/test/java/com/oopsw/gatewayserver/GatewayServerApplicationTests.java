package com.oopsw.gatewayserver;

import org.junit.jupiter.api.Test;
import com.oopsw.security.JwtTestKeys;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.http.client.ClientHttpRequestFactoryBuilder;
import org.springframework.boot.http.client.JdkClientHttpRequestFactoryBuilder;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class GatewayServerApplicationTests {
    @org.springframework.test.context.DynamicPropertySource
    static void jwtProperties(org.springframework.test.context.DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.auth.signing-key-id", JwtTestKeys.PRIMARY::kid);
        registry.add("app.auth.private-key-path", JwtTestKeys.PRIMARY::privatePath);
    }


    @Autowired
    private ClientHttpRequestFactoryBuilder<?> requestFactoryBuilder;

    @Test
    void contextLoads() {
    }

    @Test
    void 하류_호출은_연결_풀_상한이_없는_JDK_클라이언트를_쓴다() {
        // Apache HttpClient 5 기본 풀(호스트당 5)이 숨은 동시 처리 상한이 되지 않도록 JDK 클라이언트를 명시한다.
        assertThat(requestFactoryBuilder).isInstanceOf(JdkClientHttpRequestFactoryBuilder.class);
        assertThat(System.getProperty("jdk.httpclient.allowRestrictedHeaders")).contains("host");
    }

}
