package com.oopsw.noticesservice;

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
class NoticesServiceApplicationTests {
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
        assertThat(get("/notices", null).statusCode()).isEqualTo(401);
    }
    @Test void authenticatedUnimplementedRouteIsExplicit() throws Exception {
        var result = get("/notices", token(Instant.now().plusSeconds(60)));
        assertThat(result.statusCode()).isEqualTo(501);
        assertThat(result.body()).contains("ENDPOINT_NOT_IMPLEMENTED", "NoticesService");
    }
    @Test void expiredTokensAreRejected() throws Exception {
        assertThat(get("/notices", token(Instant.now().minusSeconds(60))).statusCode()).isEqualTo(401);
    }
    @Test void healthIsAvailableWithoutToken() throws Exception {
        assertThat(get("/actuator/health", null).statusCode()).isEqualTo(200);
    }
}
