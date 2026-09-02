package com.oopsw.itemservice;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.oopsw.itemservice.domain.ItemRepository;
import com.oopsw.itemservice.support.TestcontainersConfiguration;
import java.time.Instant;
import java.util.Base64;
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
    "app.auth.secret-base64="
        + "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    "app.auth.issuer=issuer",
    "app.auth.audience=audience",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate"
})
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ItemServiceIntegrationTest {

    private static final byte[] SECRET =
        "0123456789abcdef0123456789abcdef".getBytes();

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private ItemRepository itemRepository;

    @BeforeEach
    void cleanData() {
        itemRepository.deleteAllInBatch();
    }

    @Test
    void 품목_등록_목록_수정_비활성화가_동작한다() throws Exception {
        String token = token(101L, "owner@example.com");

        MvcResult createResult = mockMvc.perform(post("/items")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
            .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("sku-001", "원두", "15000.00")))
            .andExpect(status().isCreated())
            .andExpect(header().exists("Location"))
            .andExpect(jsonPath("$.sku").value("SKU-001"))
            .andExpect(jsonPath("$.status").value("ACTIVE"))
            .andReturn();

        long itemId = objectMapper.readTree(
            createResult.getResponse().getContentAsString()
        ).get("itemId").longValue();
        long version = objectMapper.readTree(
            createResult.getResponse().getContentAsString()
        ).get("version").longValue();

        mockMvc.perform(get("/items")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.totalElements").value(1))
            .andExpect(jsonPath("$.items[0].itemId").value(itemId));

        mockMvc.perform(put("/items/{itemId}", itemId)
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

        mockMvc.perform(delete("/items/{itemId}", itemId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isNoContent());

        mockMvc.perform(get("/items/{itemId}", itemId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("INACTIVE"));
    }

    @Test
    void 계정별_소유권과_SKU_유일성을_보장한다() throws Exception {
        String ownerToken = token(101L, "owner@example.com");
        String otherToken = token(202L, "other@example.com");

        MvcResult result = create(ownerToken, "SKU-001");
        long itemId = objectMapper.readTree(
            result.getResponse().getContentAsString()
        ).get("itemId").longValue();

        mockMvc.perform(post("/items")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(createJson("sku-001", "중복", "100.00")))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("SKU_ALREADY_EXISTS"));

        mockMvc.perform(get("/items/{itemId}", itemId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + otherToken))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.code").value("ITEM_NOT_FOUND"));

        create(otherToken, "SKU-001");
    }

    @Test
    void 인증과_요청검증_오류가_표준_JSON을_반환한다() throws Exception {
        mockMvc.perform(get("/items"))
            .andExpect(status().isUnauthorized())
            .andExpect(jsonPath("$.code").value(
                "AUTHENTICATION_REQUIRED"
            ));

        mockMvc.perform(post("/items")
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
        return mockMvc.perform(post("/items")
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
}
