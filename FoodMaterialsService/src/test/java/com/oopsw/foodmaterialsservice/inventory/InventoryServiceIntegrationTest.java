package com.oopsw.foodmaterialsservice.inventory;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.auth0.jwt.JWT;
import com.oopsw.security.JwtTestKeys;
import com.oopsw.foodmaterialsservice.inventory.domain.InventoryRepository;
import com.oopsw.foodmaterialsservice.inventory.domain.StockMovementRepository;
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
class InventoryServiceIntegrationTest {
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
    private InventoryRepository inventoryRepository;

    @Autowired
    private StockMovementRepository movementRepository;

    @Autowired
    private org.springframework.jdbc.core.JdbcTemplate catalogJdbc;

    @Autowired
    @org.springframework.beans.factory.annotation.Qualifier("inventoryDataSource")
    private javax.sql.DataSource inventoryDataSource;

    @BeforeEach
    void cleanData() {
        movementRepository.deleteAllInBatch();
        inventoryRepository.deleteAllInBatch();
        catalogJdbc.update("DELETE FROM item");
        catalogJdbc.update("INSERT INTO item (id, account_id, sku, name, unit_price, status, version, created_at, updated_at) VALUES (100,101,'STOCK-100','식자재',1000,'ACTIVE',0,NOW(),NOW())");
    }

    @Test
    void 재고생성_조정_원장조회가_한_흐름으로_동작한다() throws Exception {
        String token = token(101L, "owner@example.com");
        MvcResult created = create(token, 100L, 30L);
        long version = bodyLong(created, "version");

        MvcResult adjusted = mockMvc.perform(post(
                "/foodmaterials/inventories/{foodMaterialId}/adjustments",
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

        mockMvc.perform(get("/foodmaterials/inventories/{foodMaterialId}/movements", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.totalElements").value(2));

        mockMvc.perform(post("/foodmaterials/inventories/{foodMaterialId}/adjustments", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson("ADJ-001", -5L, currentVersion)))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value(
                "ADJUSTMENT_ALREADY_EXISTS"
            ));

        mockMvc.perform(post("/foodmaterials/inventories/{foodMaterialId}/adjustments", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson(
                    "ADJ-002",
                    -26L,
                    currentVersion
                )))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"));

        mockMvc.perform(get("/foodmaterials/inventories/{foodMaterialId}", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.onHandQuantity").value(25));
    }

    @Test
    void 품목검증_중복재고_계정소유권을_보장한다() throws Exception {
        String ownerToken = token(101L, "owner@example.com");
        String otherToken = token(202L, "other@example.com");
        create(ownerToken, 100L, 10L);

        mockMvc.perform(post("/foodmaterials/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(100L, 20L)))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value(
                "INVENTORY_ALREADY_EXISTS"
            ));

        mockMvc.perform(get("/foodmaterials/inventories/{foodMaterialId}", 100L)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + otherToken))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("INVENTORY_NOT_FOUND"));

        mockMvc.perform(post("/foodmaterials/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(999L, 10L)))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("FOOD_MATERIAL_NOT_FOUND"));
    }

    @Test
    void 인증과_입력검증_오류는_표준_JSON을_반환한다() throws Exception {
        mockMvc.perform(get("/foodmaterials/inventories"))
            .andExpect(status().isUnauthorized())
            .andExpect(jsonPath("$.code").value(
                "AUTHENTICATION_REQUIRED"
            ));

        mockMvc.perform(post("/foodmaterials/inventories")
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

    private MvcResult create(String token, Long foodMaterialId, Long quantity)
        throws Exception {
        return mockMvc.perform(post("/foodmaterials/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson(foodMaterialId, quantity)))
            .andExpect(status().isCreated())
            .andExpect(header().exists("Location"))
            .andExpect(jsonPath("$.foodMaterialId").value(foodMaterialId))
            .andExpect(jsonPath("$.onHandQuantity").value(quantity))
            .andReturn();
    }

    private String createJson(Long foodMaterialId, Long quantity) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
            "foodMaterialId", foodMaterialId,
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


    @Test
    void 타계정_식자재에는_재고를_등록할_수_없다() throws Exception {
        mockMvc.perform(post("/foodmaterials/inventories")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token(202L, "other@example.com"))
                .contentType(MediaType.APPLICATION_JSON).content(createJson(100L, 20L)))
            .andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("FOOD_MATERIAL_NOT_FOUND"));
        org.junit.jupiter.api.Assertions.assertEquals(0, inventoryRepository.count());
    }

    @Test
    void 목록과_원장도_계정경계를_지킨다() throws Exception {
        create(token(101L, "owner@example.com"), 100L, 20L);
        String other = token(202L, "other@example.com");
        mockMvc.perform(get("/foodmaterials/inventories").header(HttpHeaders.AUTHORIZATION,"Bearer "+other))
            .andExpect(status().isOk()).andExpect(jsonPath("$.totalElements").value(0));
        mockMvc.perform(get("/foodmaterials/inventories/100/movements").header(HttpHeaders.AUTHORIZATION,"Bearer "+other))
            .andExpect(status().isNotFound());
        mockMvc.perform(post("/foodmaterials/inventories/100/adjustments")
                .header(HttpHeaders.AUTHORIZATION,"Bearer "+other).contentType(MediaType.APPLICATION_JSON)
                .content(adjustmentJson("OTHER-1", -1L, 0L)))
            .andExpect(status().isNotFound());
    }

    @Test
    void 같은버전_동시조정은_한건만_반영된다() throws Exception {
        String access=token(101L,"owner@example.com");
        create(access,100L,20L);
        var barrier=new java.util.concurrent.CyclicBarrier(10);
        try(var executor=java.util.concurrent.Executors.newFixedThreadPool(10)) {
            var futures=new java.util.ArrayList<java.util.concurrent.Future<MvcResult>>();
            for(int i=0;i<10;i++) {
                String requestId="RACE-"+i;
                futures.add(executor.submit(() -> {
                    barrier.await(10,java.util.concurrent.TimeUnit.SECONDS);
                    return mockMvc.perform(post("/foodmaterials/inventories/100/adjustments")
                        .header(HttpHeaders.AUTHORIZATION,"Bearer "+access).contentType(MediaType.APPLICATION_JSON)
                        .content(adjustmentJson(requestId,-1L,0L))).andReturn();
                }));
            }
            int success=0,conflict=0;
            for(var f:futures) {
                var response=f.get(30,java.util.concurrent.TimeUnit.SECONDS).getResponse();
                if(response.getStatus()==200) success++;
                else {
                    org.junit.jupiter.api.Assertions.assertEquals(409,response.getStatus());
                    org.junit.jupiter.api.Assertions.assertEquals("INVENTORY_CONFLICT",objectMapper.readTree(response.getContentAsString()).get("code").asString());
                    conflict++;
                }
            }
            org.junit.jupiter.api.Assertions.assertEquals(1,success);
            org.junit.jupiter.api.Assertions.assertEquals(9,conflict);
        }
        mockMvc.perform(get("/foodmaterials/inventories/100").header(HttpHeaders.AUTHORIZATION,"Bearer "+access))
            .andExpect(status().isOk()).andExpect(jsonPath("$.onHandQuantity").value(19));
        org.junit.jupiter.api.Assertions.assertEquals(2,movementRepository.count());
    }

    @Test
    void 원장저장_실패시_수량변경도_롤백된다() throws Exception {
        String access=token(101L,"owner@example.com");
        create(access,100L,20L);
        var jdbc=new org.springframework.jdbc.core.JdbcTemplate(inventoryDataSource);
        jdbc.execute("CREATE TRIGGER reject_movement BEFORE INSERT ON stock_movement FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'test failure'");
        try {
            mockMvc.perform(post("/foodmaterials/inventories/100/adjustments")
                    .header(HttpHeaders.AUTHORIZATION,"Bearer "+access).contentType(MediaType.APPLICATION_JSON)
                    .content(adjustmentJson("ROLLBACK-1",-1L,0L)))
                .andExpect(status().is5xxServerError());
            mockMvc.perform(get("/foodmaterials/inventories/100").header(HttpHeaders.AUTHORIZATION,"Bearer "+access))
                .andExpect(status().isOk()).andExpect(jsonPath("$.onHandQuantity").value(20))
                .andExpect(jsonPath("$.version").value(0));
            org.junit.jupiter.api.Assertions.assertEquals(1,movementRepository.count());
        } finally { jdbc.execute("DROP TRIGGER reject_movement"); }
    }
}
