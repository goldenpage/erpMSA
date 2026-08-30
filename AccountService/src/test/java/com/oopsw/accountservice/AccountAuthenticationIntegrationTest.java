package com.oopsw.accountservice;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.cookie;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.oopsw.accountservice.entity.AccountRepository;
import com.oopsw.accountservice.outbox.AccountOutboxRepository;
import com.oopsw.accountservice.outbox.OutboxStatus;
import com.oopsw.accountservice.support.TestcontainersConfiguration;
import jakarta.servlet.http.Cookie;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(properties = {
    "app.auth.secret-base64="
        + "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    "app.auth.secure-cookie=false",
    "app.kafka.outbox.publish-delay=100ms",
    "app.kafka.outbox.retry-delay=100ms",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate"
})
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class AccountAuthenticationIntegrationTest {

    private static final String EMAIL = "owner@example.com";
    private static final String PASSWORD = "Test1234!";
    private static final String REFRESH_COOKIE = "refreshToken";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

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

        RedisConnection connection = Objects.requireNonNull(
            redisTemplate.getConnectionFactory()
        ).getConnection();

        try {
            connection.serverCommands().flushDb();
        } finally {
            connection.close();
        }
    }

    @Test
    void 회원가입하면_DB에_계정이_저장되고_Kafka_Outbox가_발행된다()
        throws Exception {

        mockMvc.perform(post("/account/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(registerJson(EMAIL, "1234567890")))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.accountId").isNumber())
            .andExpect(jsonPath("$.email").value(EMAIL))
            .andExpect(jsonPath("$.status").value("ACTIVE"));

        assertThat(accountRepository.findByEmail(EMAIL)).isPresent();

        await()
            .atMost(Duration.ofSeconds(15))
            .untilAsserted(() -> {
                var events = outboxRepository.findAll();

                assertThat(events).hasSize(1);
                assertThat(events.getFirst().getStatus())
                    .isEqualTo(OutboxStatus.PUBLISHED);
                assertThat(events.getFirst().getEventType())
                    .isEqualTo("AccountRegistered");
            });
    }

    @Test
    void 로그인_인증조회_RefreshToken회전_로그아웃이_동작한다()
        throws Exception {

        register(EMAIL, "1234567890");

        MvcResult loginResult = mockMvc.perform(post("/account/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(loginJson(EMAIL, PASSWORD)))
            .andExpect(status().isOk())
            .andExpect(header().exists(HttpHeaders.AUTHORIZATION))
            .andExpect(jsonPath("$.tokenType").value("Bearer"))
            .andExpect(jsonPath("$.accessToken").isNotEmpty())
            .andExpect(jsonPath("$.expiresIn").value(900))
            .andExpect(cookie().httpOnly(REFRESH_COOKIE, true))
            .andExpect(cookie().secure(REFRESH_COOKIE, false))
            .andReturn();

        String accessToken = accessToken(loginResult);
        Cookie firstRefreshToken = refreshCookie(loginResult);

        mockMvc.perform(get("/account/auth/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + accessToken))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.accountId").isNumber())
            .andExpect(jsonPath("$.email").value(EMAIL));

        MvcResult refreshResult = mockMvc.perform(post("/account/auth/refresh")
                .cookie(firstRefreshToken))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.accessToken").isNotEmpty())
            .andExpect(cookie().exists(REFRESH_COOKIE))
            .andReturn();

        Cookie rotatedRefreshToken = refreshCookie(refreshResult);

        mockMvc.perform(post("/account/auth/refresh")
                .cookie(firstRefreshToken))
            .andExpect(status().isUnauthorized());

        mockMvc.perform(post("/account/auth/logout")
                .cookie(rotatedRefreshToken))
            .andExpect(status().isNoContent())
            .andExpect(cookie().maxAge(REFRESH_COOKIE, 0));

        mockMvc.perform(post("/account/auth/refresh")
                .cookie(rotatedRefreshToken))
            .andExpect(status().isUnauthorized());
    }

    @Test
    void 중복_이메일과_잘못된_요청은_거절한다() throws Exception {
        register(EMAIL, "1234567890");

        mockMvc.perform(post("/account/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(registerJson(EMAIL, "0987654321")))
            .andExpect(status().isConflict());

        mockMvc.perform(post("/account/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(registerJson("not-an-email", "123")))
            .andExpect(status().isBadRequest());

        assertThat(accountRepository.count()).isEqualTo(1);
    }

    private void register(String email, String businessId) throws Exception {
        mockMvc.perform(post("/account/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(registerJson(email, businessId)))
            .andExpect(status().isCreated());
    }

    private String registerJson(String email, String businessId)
        throws Exception {

        return objectMapper.writeValueAsString(Map.of(
            "email", email,
            "businessId", businessId,
            "password", PASSWORD,
            "name", "테스트 점주",
            "phone", "01012345678",
            "storeName", "테스트 매장",
            "storeType", "RETAIL",
            "storeCategory", "TEST",
            "marketingAgreed", true
        ));
    }

    private String loginJson(String email, String password)
        throws Exception {

        return objectMapper.writeValueAsString(Map.of(
            "email", email,
            "password", password
        ));
    }

    private String accessToken(MvcResult result) throws Exception {
        return objectMapper.readTree(
            result.getResponse().getContentAsString()
        ).get("accessToken").stringValue();
    }

    private Cookie refreshCookie(MvcResult result) {
        return Objects.requireNonNull(
            result.getResponse().getCookie(REFRESH_COOKIE)
        );
    }
}
