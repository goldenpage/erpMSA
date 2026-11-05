package com.oopsw.billsservice;

import com.auth0.jwt.JWT;
import com.oopsw.security.JwtTestKeys;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {"eureka.client.enabled=false", "spring.cloud.discovery.enabled=false"})
@org.junit.jupiter.api.Tag("integration")
class BillsServiceApplicationTests {
    @LocalServerPort int port;
    @DynamicPropertySource static void keys(DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", () -> JwtTestKeys.PRIMARY.publicDirectory());
    }
    HttpResponse<String> get(String path, String token) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path));
        if (token != null) request.header("Authorization", "Bearer " + token);
        return HttpClient.newHttpClient().send(request.GET().build(), HttpResponse.BodyHandlers.ofString());
    }
    String token(Instant expires) {
        var key = JwtTestKeys.PRIMARY;
        return JWT.create().withKeyId(key.kid()).withIssuer("kosta-erp-account").withAudience("kosta-erp-api")
            .withSubject("1").withClaim("email", "test@example.com").withClaim("role", "ROLE_USER")
            .withClaim("token_type", "access").withIssuedAt(Instant.now().minusSeconds(120))
            .withExpiresAt(expires).sign(key.algorithm());
    }
    @Test void unauthenticatedRequestsAreRejected() throws Exception {
        assertThat(get("/bills", null).statusCode()).isEqualTo(401);
    }
    @Test void authenticatedUnimplementedRouteIsExplicit() throws Exception {
        var result = get("/bills", token(Instant.now().plusSeconds(60)));
        assertThat(result.statusCode()).isEqualTo(501);
        assertThat(result.body()).contains("ENDPOINT_NOT_IMPLEMENTED", "BillsService");
    }
    @Test void expiredTokensAreRejected() throws Exception {
        assertThat(get("/bills", token(Instant.now().minusSeconds(60))).statusCode()).isEqualTo(401);
    }
    @Test void healthIsAvailableWithoutToken() throws Exception {
        assertThat(get("/actuator/health", null).statusCode()).isEqualTo(200);
    }

    @org.springframework.beans.factory.annotation.Autowired
    org.springframework.context.ApplicationContext drainContext;

    /** 종료 시 Eureka DOWN 알림 후 drain(shared/service-foundation)이 이 서비스에 연결됐는지 확인한다. */
    @Test void 종료_시_웹_서버보다_먼저_Eureka_DOWN_후_drain하도록_연결된다() {
        var drain = drainContext.getBean(com.oopsw.foundation.DiscoveryDrainLifecycle.class);
        var graceful = drainContext.getBeansOfType(org.springframework.context.SmartLifecycle.class).values().stream()
            .filter(bean -> bean.getClass().getSimpleName().equals("WebServerGracefulShutdownLifecycle"))
            .findFirst().orElseThrow();
        // 높은 phase가 먼저 멈춘다. drain이 끝난 뒤에 웹 서버 graceful shutdown이 시작된다.
        assertThat(drain.getPhase()).isGreaterThan(graceful.getPhase());
        assertThat(drain.drain()).isEqualTo(java.time.Duration.ofSeconds(15));
        // 테스트는 Eureka 클라이언트를 끈다. 알릴 대상이 없으면 기다리지 않고 바로 끝난다.
        assertThat(drainContext.getBeanProvider(com.netflix.appinfo.ApplicationInfoManager.class).getIfAvailable()).isNull();
        long started = System.nanoTime();
        drain.stop();
        assertThat(java.time.Duration.ofNanos(System.nanoTime() - started)).isLessThan(java.time.Duration.ofSeconds(1));
        drain.start();
    }
}
