package com.oopsw.inventoryservice;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import com.oopsw.inventoryservice.client.ItemCatalogClient;
import com.oopsw.inventoryservice.domain.InventoryRepository;
import com.oopsw.inventoryservice.domain.StockMovementRepository;
import com.oopsw.inventoryservice.support.TestcontainersConfiguration;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(properties = {
    "app.auth.secret-base64="
        + "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    "app.auth.issuer=issuer",
    "app.auth.audience=audience",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate"
})
@AutoConfigureMockMvc
@Import({
    TestcontainersConfiguration.class,
    InventoryServiceIntegrationTest.OwnedItemClientConfiguration.class
})
class InventoryServiceIntegrationTest {

    private static final byte[] SECRET =
        "0123456789abcdef0123456789abcdef".getBytes();

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private InventoryRepository inventoryRepository;

    @Autowired
    private StockMovementRepository movementRepository;

    @BeforeEach
    void cleanData() {
        movementRepository.deleteAllInBatch();
        inventoryRepository.deleteAllInBatch();
    }

    @Test
    void 재고생성_조정_원장조회가_한_흐름으로_동작한다() throws Exception {
        String token = token(101L, "owner@example.com");
        MvcResult created = create(token, 100L, 30L);
        long version = bodyLong(created, "version");

        MvcResult adjusted = mockMvc.perform(post(
                "/inventories/{itemId}/adjustments",
                100L
            )
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson("ADJ-001", -5L, version)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.inventory.onHandQuantity").value(25))
            .andExpect(jsonPath("$.inventory.version").value(1))
            .andExpect(jsonPath("$.movement.quantityBefore").value(30))
            .andExpect(jsonPath("$.movement.quantityAfter").value(25))
            .andReturn();

        long currentVersion = objectMapper.readTree(
            adjusted.getResponse().getContentAsString()
        ).get("inventory").get("version").longValue();

        mockMvc.perform(get("/inventories/{itemId}/movements", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.totalElements").value(2));

        mockMvc.perform(post("/inventories/{itemId}/adjustments", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson("ADJ-001", -5L, currentVersion)))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value(
                "ADJUSTMENT_ALREADY_EXISTS"
            ));

        mockMvc.perform(post("/inventories/{itemId}/adjustments", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson(
                    "ADJ-002",
                    -26L,
                    currentVersion
                )))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"));

        mockMvc.perform(get("/inventories/{itemId}", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.onHandQuantity").value(25));
    }

    @Test
    void 품목검증_중복재고_계정소유권을_보장한다() throws Exception {
        String ownerToken = token(101L, "owner@example.com");
        String otherToken = token(202L, "other@example.com");
        create(ownerToken, 100L, 10L);

        mockMvc.perform(post("/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(100L, 20L)))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value(
                "INVENTORY_ALREADY_EXISTS"
            ));

        mockMvc.perform(get("/inventories/{itemId}", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + otherToken))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("INVENTORY_NOT_FOUND"));

        mockMvc.perform(post("/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(999L, 10L)))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("ITEM_NOT_FOUND"));
    }

    @Test
    void 인증과_입력검증_오류는_표준_JSON을_반환한다() throws Exception {
        mockMvc.perform(get("/inventories"))
            .andExpect(status().isUnauthorized())
            .andExpect(jsonPath("$.code").value(
                "AUTHENTICATION_REQUIRED"
            ));

        mockMvc.perform(post("/inventories")
                .header(
                    HttpHeaders.AUTHORIZATION,
                    "Bearer " + token(101L, "owner@example.com")
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(-1L, -1L)))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
            .andExpect(jsonPath("$.fieldErrors").isNotEmpty());
    }

    private MvcResult create(String token, Long itemId, Long quantity)
        throws Exception {
        return mockMvc.perform(post("/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(itemId, quantity)))
            .andExpect(status().isCreated())
            .andExpect(header().exists("Location"))
            .andExpect(jsonPath("$.itemId").value(itemId))
            .andExpect(jsonPath("$.onHandQuantity").value(quantity))
            .andReturn();
    }

    private String createJson(Long itemId, Long quantity) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
            "itemId", itemId,
            "initialQuantity", quantity
        ));
    }

    private String adjustmentJson(
        String requestId,
        Long delta,
        Long version
    ) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
            "requestId", requestId,
            "quantityDelta", delta,
            "reason", "통합 테스트 조정",
            "version", version
        ));
    }

    private long bodyLong(MvcResult result, String field) throws Exception {
        return objectMapper.readTree(
            result.getResponse().getContentAsString()
        ).get(field).longValue();
    }

    private String token(Long accountId, String email) {
        Instant now = Instant.now();
        return JWT.create()
            .withIssuer("issuer")
            .withAudience("audience")
            .withSubject(accountId.toString())
            .withIssuedAt(now)
            .withExpiresAt(now.plusSeconds(300))
            .withClaim("token_type", "access")
            .withClaim("email", email)
            .withClaim("role", "ROLE_USER")
            .sign(Algorithm.HMAC256(SECRET));
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class OwnedItemClientConfiguration {

        @Bean
        @Primary
        ItemCatalogClient itemCatalogClient() {
            return (itemId, authorization) -> {
                if (itemId == 999L) {
                    throw new ApiException(ApiErrorCode.ITEM_NOT_FOUND);
                }
            };
        }
    }
}
