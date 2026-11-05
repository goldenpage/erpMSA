package com.oopsw.gatewayserver;

import org.junit.jupiter.api.Test;
import com.oopsw.security.JwtTestKeys;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.http.client.ClientHttpRequestFactoryBuilder;
import org.springframework.boot.http.client.JdkClientHttpRequestFactoryBuilder;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.cloud.gateway.server.mvc.filter.BeforeFilterFunctions.uri;
import static org.springframework.cloud.gateway.server.mvc.handler.GatewayRouterFunctions.route;
import static org.springframework.cloud.gateway.server.mvc.handler.HandlerFunctions.http;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.auth0.jwt.JWT;
import java.time.Instant;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerResponse;

@SpringBootTest
@AutoConfigureMockMvc
@Import(GatewayServerApplicationTests.UnreachableRoute.class)
@org.junit.jupiter.api.Tag("integration")
class GatewayServerApplicationTests {

    /** 연결이 즉시 거부되는 하류로 보내는 시험 경로. 실제 라우팅·예외 처리 경로를 그대로 탄다. */
    @TestConfiguration
    static class UnreachableRoute {
        @Bean
        RouterFunction<ServerResponse> unreachableAccountRoute() {
            return route("unreachable-test").GET("/account/unreachable-test", http())
                .before(uri("http://127.0.0.1:1")).build();
        }
    }

    @Autowired
    private MockMvc mockMvc;

    @Test
    void 하류에_연결할_수_없으면_500_대신_503과_재시도_시간을_돌려준다() throws Exception {
        Instant now = Instant.now();
        String token = JWT.create().withKeyId(JwtTestKeys.PRIMARY.kid())
            .withIssuer("kosta-erp-account").withAudience("kosta-erp-api").withSubject("1")
            .withIssuedAt(now).withExpiresAt(now.plusSeconds(300))
            .withClaim("token_type", "access").withClaim("email", "user@example.com").withClaim("role", "ROLE_USER")
            .sign(JwtTestKeys.PRIMARY.algorithm());

        mockMvc.perform(get("/account/unreachable-test").header("Authorization", "Bearer " + token))
            .andExpect(status().isServiceUnavailable())
            .andExpect(header().string("Retry-After", "1"))
            .andExpect(jsonPath("$.code").value("UPSTREAM_UNAVAILABLE"));
    }
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
