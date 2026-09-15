package com.oopsw.gatewayserver;

import org.junit.jupiter.api.Test;
import com.oopsw.security.JwtTestKeys;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class GatewayServerApplicationTests {
    @org.springframework.test.context.DynamicPropertySource
    static void jwtProperties(org.springframework.test.context.DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.auth.signing-key-id", JwtTestKeys.PRIMARY::kid);
        registry.add("app.auth.private-key-path", JwtTestKeys.PRIMARY::privatePath);
    }


    @Test
    void contextLoads() {
    }

}
