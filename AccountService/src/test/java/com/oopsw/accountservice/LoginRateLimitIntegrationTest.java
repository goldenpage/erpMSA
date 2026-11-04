package com.oopsw.accountservice;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.oopsw.accountservice.entity.AccountRepository;
import com.oopsw.accountservice.outbox.AccountOutboxRepository;
import com.oopsw.accountservice.support.TestcontainersConfiguration;
import com.oopsw.security.JwtTestKeys;
import java.util.Objects;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

/** 실제 Redis·MariaDB에서 로그인·가입 시도 제한을 검사한다. 구간 경계에 걸리지 않도록 IP 구간을 1시간으로 둔다. */
@SpringBootTest(properties = {
    "app.auth.secure-cookie=false",
    "app.kafka.outbox.publish-delay=100ms",
    "app.kafka.outbox.retry-delay=100ms",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate",
    "app.auth.rate-limit.login-per-ip=4",
    "app.auth.rate-limit.register-per-ip=2",
    "app.auth.rate-limit.ip-window=1h",
    "app.auth.rate-limit.failures-before-lock=3",
    "app.auth.rate-limit.lock-initial=1m",
    "app.auth.rate-limit.lock-max=15m"
})
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class LoginRateLimitIntegrationTest {

    @DynamicPropertySource
    static void jwtProperties(DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.auth.signing-key-id", JwtTestKeys.PRIMARY::kid);
        registry.add("app.auth.private-key-path", JwtTestKeys.PRIMARY::privatePath);
    }

    private static final String PASSWORD = "Test1234!";
    private int ipSequence;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private AccountRepository accountRepository;

    @Autowired
    private AccountOutboxRepository outboxRepository;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @BeforeEach
    void cleanData() {
        outboxRepository.deleteAllInBatch();
        accountRepository.deleteAllInBatch();
        RedisConnection connection = Objects.requireNonNull(redisTemplate.getConnectionFactory()).getConnection();
        try {
            connection.serverCommands().flushDb();
        } finally {
            connection.close();
        }
    }

    /** 매 호출 다른 클라이언트 주소. 같은 IP 제한에 걸리지 않게 계정 기준 시험을 분리한다. */
    private String freshIp() {
        ipSequence++;
        return "198.51.100." + ipSequence;
    }

    private MockHttpServletRequestBuilder via(MockHttpServletRequestBuilder builder, String remote, String clientAddress) {
        return builder.with(request -> {
            request.setRemoteAddr(remote);
            return request;
        }).header("X-Client-Address", clientAddress);
    }

    private int login(String email, String password, String clientIp) throws Exception {
        return loginResult(email, password, "127.0.0.1", clientIp).getResponse().getStatus();
    }

    private MvcResult loginResult(String email, String password, String remote, String clientIp) throws Exception {
        return mockMvc.perform(via(post("/account/auth/login"), remote, clientIp)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\":\"" + email + "\",\"password\":\"" + password + "\"}"))
            .andReturn();
    }

    private int register(String email, String businessId, String clientIp) throws Exception {
        return mockMvc.perform(via(post("/account/auth/register"), "127.0.0.1", clientIp)
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"email":"%s","businessId":"%s","password":"%s","name":"테스트","phone":"01012345678",
                     "storeName":"매장","storeType":"RESTAURANT","storeCategory":"KOREAN","marketingAgreed":false}
                    """.formatted(email, businessId, PASSWORD)))
            .andReturn().getResponse().getStatus();
    }

    @Test
    void 같은_이메일로_연속_실패하면_올바른_비밀번호도_잠시_거절하고_남은_시간을_알린다() throws Exception {
        assertThat(register("owner@example.com", "1000000001", freshIp())).isEqualTo(201);
        for (int i = 0; i < 3; i++) {
            assertThat(login("owner@example.com", "wrong-password", freshIp())).isEqualTo(401);
        }

        MvcResult limited = loginResult("owner@example.com", PASSWORD, "127.0.0.1", freshIp());

        assertThat(limited.getResponse().getStatus()).isEqualTo(429);
        assertThat(limited.getResponse().getContentAsString()).contains("LOGIN_RATE_LIMITED");
        long retryAfter = Long.parseLong(Objects.requireNonNull(limited.getResponse().getHeader("Retry-After")));
        assertThat(retryAfter).isBetween(1L, 60L);
    }

    @Test
    void 없는_이메일도_같은_방식으로_실패를_세서_가입_여부를_드러내지_않는다() throws Exception {
        for (int i = 0; i < 3; i++) {
            assertThat(login("nobody@example.com", "wrong-password", freshIp())).isEqualTo(401);
        }
        assertThat(login("nobody@example.com", "wrong-password", freshIp())).isEqualTo(429);
    }

    @Test
    void 로그인에_성공하면_실패_기록을_초기화한다() throws Exception {
        assertThat(register("owner@example.com", "1000000001", freshIp())).isEqualTo(201);
        assertThat(login("owner@example.com", "wrong-password", freshIp())).isEqualTo(401);
        assertThat(login("owner@example.com", "wrong-password", freshIp())).isEqualTo(401);
        assertThat(login("owner@example.com", PASSWORD, freshIp())).isEqualTo(200);
        assertThat(login("owner@example.com", "wrong-password", freshIp())).isEqualTo(401);
        assertThat(login("owner@example.com", "wrong-password", freshIp())).isEqualTo(401);
        assertThat(login("owner@example.com", PASSWORD, freshIp())).isEqualTo(200);
    }

    @Test
    void 같은_IP의_로그인은_구간당_상한까지만_처리하고_다른_IP는_영향받지_않는다() throws Exception {
        String attacker = "203.0.113.10";
        for (int i = 0; i < 4; i++) {
            assertThat(login("spray" + i + "@example.com", "wrong-password", attacker)).isEqualTo(401);
        }
        assertThat(login("spray9@example.com", "wrong-password", attacker)).isEqualTo(429);
        assertThat(login("other@example.com", "wrong-password", "203.0.113.11")).isEqualTo(401);
    }

    @Test
    void 신뢰하지_않는_연결이_보낸_클라이언트_주소는_무시한다() throws Exception {
        // Gateway가 아닌 곳에서 직접 접속해 매번 다른 주소를 주장해도 실제 연결 주소로 센다.
        for (int i = 0; i < 4; i++) {
            assertThat(loginResult("spoof" + i + "@example.com", "wrong-password", "203.0.113.50", freshIp())
                .getResponse().getStatus()).isEqualTo(401);
        }
        assertThat(loginResult("spoof9@example.com", "wrong-password", "203.0.113.50", freshIp())
            .getResponse().getStatus()).isEqualTo(429);
    }

    @Test
    void 같은_IP의_회원가입은_구간당_상한까지만_처리한다() throws Exception {
        String ip = "203.0.113.20";
        assertThat(register("a@example.com", "1000000001", ip)).isEqualTo(201);
        assertThat(register("b@example.com", "1000000002", ip)).isEqualTo(201);
        mockMvc.perform(via(post("/account/auth/register"), "127.0.0.1", ip)
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"email":"c@example.com","businessId":"1000000003","password":"%s","name":"테스트",
                     "storeName":"매장","marketingAgreed":false}
                    """.formatted(PASSWORD)))
            .andExpect(status().isTooManyRequests())
            .andExpect(jsonPath("$.code").value("REGISTER_RATE_LIMITED"));
        assertThat(accountRepository.findByEmail("c@example.com")).isEmpty();
    }
}
