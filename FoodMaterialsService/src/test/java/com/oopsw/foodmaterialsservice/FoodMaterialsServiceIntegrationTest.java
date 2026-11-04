package com.oopsw.foodmaterialsservice;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.hasItem;

import com.auth0.jwt.JWT;
import com.oopsw.security.JwtTestKeys;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialRepository;
import com.oopsw.foodmaterialsservice.support.TestcontainersConfiguration;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(properties = {
    "app.auth.issuer=issuer",
    "app.auth.audience=audience",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate"
})
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class FoodMaterialsServiceIntegrationTest {
    @org.springframework.test.context.DynamicPropertySource
    static void jwtProperties(org.springframework.test.context.DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.auth.signing-key-id", JwtTestKeys.PRIMARY::kid);
        registry.add("app.auth.private-key-path", JwtTestKeys.PRIMARY::privatePath);
    }



    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private FoodMaterialRepository itemRepository;

    @Autowired
    private org.springframework.jdbc.core.JdbcTemplate jdbc;

    @BeforeEach
    void cleanData() {
        itemRepository.deleteAllInBatch();
    }

    @Test
    void 목록_범위_오류는_400이며_기존_데이터를_보존한다() throws Exception {
        String access = token(101L, "owner@example.com");
        create(access, "VALIDATION-PAGE");
        var before = jdbc.queryForList("SELECT * FROM item ORDER BY id");
        for (String[] invalid : new String[][] {{"page", "-1"}, {"size", "0"}, {"size", "101"}}) {
            mockMvc.perform(get("/foodmaterials").param(invalid[0], invalid[1])
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + access))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.fieldErrors[*].field").value(hasItem(invalid[0])));
        }
        assertThat(jdbc.queryForList("SELECT * FROM item ORDER BY id")).isEqualTo(before);
    }

    @Test
    void 잘못된_품목_ID는_조회_수정_삭제에서_400을_반환한다() throws Exception {
        String access = token(101L, "owner@example.com");
        create(access, "VALIDATION-ID");
        var before = jdbc.queryForList("SELECT * FROM item ORDER BY id");
        for (long id : new long[] {0L, -1L}) {
            var requests = java.util.List.of(
                get("/foodmaterials/{foodMaterialId}", id),
                put("/foodmaterials/{foodMaterialId}", id)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(updateJson("수정 시도", "100.00", "ACTIVE", 0L)),
                delete("/foodmaterials/{foodMaterialId}", id)
            );
            for (var request : requests) {
                mockMvc.perform(request.header(HttpHeaders.AUTHORIZATION, "Bearer " + access))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                    .andExpect(jsonPath("$.fieldErrors[*].field").value(hasItem("foodMaterialId")));
            }
        }
        assertThat(jdbc.queryForList("SELECT * FROM item ORDER BY id")).isEqualTo(before);
    }

    @Test
    void 정상_페이지_경계는_200을_반환한다() throws Exception {
        String access = token(101L, "owner@example.com");
        create(access, "VALIDATION-BOUNDARY");
        for (String size : new String[] {"1", "100"}) {
            mockMvc.perform(get("/foodmaterials").param("page", "0").param("size", size)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + access))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalElements").value(1));
        }
    }

    @Test
    void 잘못된_수정_body의_필드_오류_계약을_유지한다() throws Exception {
        String access = token(101L, "owner@example.com");
        var created = create(access, "VALIDATION-BODY");
        long id = objectMapper.readTree(created.getResponse().getContentAsString())
            .get("foodMaterialId").longValue();
        var before = jdbc.queryForList("SELECT * FROM item ORDER BY id");
        mockMvc.perform(put("/foodmaterials/{foodMaterialId}", id)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + access)
                .contentType(MediaType.APPLICATION_JSON)
                .content(updateJson("", "100.00", "ACTIVE", 0L)))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
            .andExpect(jsonPath("$.fieldErrors[*].field").value(hasItem("name")));
        assertThat(jdbc.queryForList("SELECT * FROM item ORDER BY id")).isEqualTo(before);
    }

    @Test
    void 같은_생성시각도_페이지_순서가_안정적이다() throws Exception {
        String access = token(101L, "owner@example.com");
        long[] ids = new long[2];
        for (int i = 0; i < 2; i++) {
            MvcResult result = mockMvc.perform(post("/foodmaterials")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + access)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("tie-" + i, "동일시각 품목", "1000.00")))
                .andExpect(status().isCreated()).andReturn();
            ids[i] = objectMapper.readTree(result.getResponse().getContentAsString()).get("foodMaterialId").longValue();
        }
        jdbc.update("UPDATE item SET created_at='2026-01-01 00:00:00' WHERE account_id=101");
        for (int page = 0; page < 2; page++) {
            mockMvc.perform(get("/foodmaterials").param("page", String.valueOf(page)).param("size", "1").param("status", "ACTIVE")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + access))
                .andExpect(status().isOk()).andExpect(jsonPath("$.foodMaterials[0].foodMaterialId").value(ids[1-page]));
        }
    }

    @Test
    void 품목_등록_목록_수정_비활성화가_동작한다() throws Exception {
        String token = token(101L, "owner@example.com");

        MvcResult createResult = mockMvc.perform(post("/foodmaterials")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
            .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("sku-001", "원두", "15000.00")))
            .andExpect(status().isCreated())
            .andExpect(header().exists("Location"))
            .andExpect(jsonPath("$.sku").value("SKU-001"))
            .andExpect(jsonPath("$.status").value("ACTIVE"))
            .andReturn();

        long foodMaterialId = objectMapper.readTree(
            createResult.getResponse().getContentAsString()
        ).get("foodMaterialId").longValue();
        long version = objectMapper.readTree(
            createResult.getResponse().getContentAsString()
        ).get("version").longValue();

        mockMvc.perform(get("/foodmaterials")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.totalElements").value(1))
            .andExpect(jsonPath("$.foodMaterials[0].foodMaterialId").value(foodMaterialId));

        mockMvc.perform(put("/foodmaterials/{foodMaterialId}", foodMaterialId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(updateJson(
                    "프리미엄 원두",
                    "18000.00",
                    "ACTIVE",
                    version
                )))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.name").value("프리미엄 원두"))
            .andExpect(jsonPath("$.unitPrice").value(18000.00));

        mockMvc.perform(delete("/foodmaterials/{foodMaterialId}", foodMaterialId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isNoContent());

        mockMvc.perform(get("/foodmaterials/{foodMaterialId}", foodMaterialId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("INACTIVE"));
    }

    @Test
    void 계정별_소유권과_SKU_유일성을_보장한다() throws Exception {
        String ownerToken = token(101L, "owner@example.com");
        String otherToken = token(202L, "other@example.com");

        MvcResult result = create(ownerToken, "SKU-001");
        long foodMaterialId = objectMapper.readTree(
            result.getResponse().getContentAsString()
        ).get("foodMaterialId").longValue();

        mockMvc.perform(post("/foodmaterials")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("sku-001", "중복", "100.00")))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("SKU_ALREADY_EXISTS"));

        mockMvc.perform(get("/foodmaterials/{foodMaterialId}", foodMaterialId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + otherToken))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("FOOD_MATERIAL_NOT_FOUND"));

        create(otherToken, "SKU-001");
    }

    @Test
    void 인증과_요청검증_오류가_표준_JSON을_반환한다() throws Exception {
        mockMvc.perform(get("/foodmaterials"))
            .andExpect(status().isUnauthorized())
            .andExpect(jsonPath("$.code").value(
                "AUTHENTICATION_REQUIRED"
            ));

        mockMvc.perform(post("/foodmaterials")
                .header(
                    HttpHeaders.AUTHORIZATION,
                    "Bearer " + token(101L, "owner@example.com")
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("bad sku", "", "-1.00")))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
            .andExpect(jsonPath("$.fieldErrors").isNotEmpty());
    }

    private MvcResult create(String token, String sku) throws Exception {
        return mockMvc.perform(post("/foodmaterials")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(sku, "원두", "15000.00")))
            .andExpect(status().isCreated())
            .andReturn();
    }

    private String createJson(String sku, String name, String unitPrice)
        throws Exception {
        return objectMapper.writeValueAsString(Map.of(
            "sku", sku,
            "name", name,
            "description", "테스트 품목",
            "unitPrice", unitPrice
        ));
    }

    private String updateJson(
        String name,
        String unitPrice,
        String status,
        long version
    ) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
            "name", name,
            "description", "수정된 품목",
            "unitPrice", unitPrice,
            "status", status,
            "version", version
        ));
    }

    private String token(Long accountId, String email) {
        Instant now = Instant.now();
        return JWT.create().withKeyId(JwtTestKeys.PRIMARY.kid())
            .withIssuer("issuer")
            .withAudience("audience")
            .withSubject(accountId.toString())
            .withIssuedAt(now)
            .withExpiresAt(now.plusSeconds(300))
            .withClaim("token_type", "access")
            .withClaim("email", email)
            .withClaim("role", "ROLE_USER")
            .sign(JwtTestKeys.PRIMARY.algorithm());
    }

    @org.springframework.beans.factory.annotation.Autowired
    org.springframework.context.ApplicationContext drainContext;

    /** 종료 시 Eureka DOWN 알림 후 drain(shared/service-foundation)이 이 서비스에 연결됐는지 확인한다. */
    @Test void 종료_시_웹_서버보다_먼저_Eureka_DOWN_후_drain하도록_연결된다() {
        var drain = drainContext.getBean(com.oopsw.foundation.DiscoveryDrainLifecycle.class);
        // MockMvc 테스트라 웹 서버가 없다. 웹 서버 graceful shutdown phase(Integer.MAX_VALUE - 1024)와 비교한다.
        // 높은 phase가 먼저 멈춘다. drain이 끝난 뒤에 웹 서버 graceful shutdown이 시작된다.
        assertThat(drain.getPhase()).isGreaterThan(Integer.MAX_VALUE - 1024);
        assertThat(drain.drain()).isEqualTo(java.time.Duration.ofSeconds(15));
        // 테스트는 Eureka 클라이언트를 끈다. 알릴 대상이 없으면 기다리지 않고 바로 끝난다.
        assertThat(drainContext.getBeanProvider(com.netflix.appinfo.ApplicationInfoManager.class).getIfAvailable()).isNull();
        long started = System.nanoTime();
        drain.stop();
        assertThat(java.time.Duration.ofNanos(System.nanoTime() - started)).isLessThan(java.time.Duration.ofSeconds(1));
        drain.start();
    }
}
