package com.oopsw.foodmaterialsservice.inventory;

import static org.junit.jupiter.api.Assertions.assertEquals;
import com.oopsw.foodmaterialsservice.inventory.service.InventoryService;
import com.oopsw.foodmaterialsservice.support.TestcontainersConfiguration;
import com.oopsw.foodmaterialsservice.support.LegacyMigrationFixture;
import org.testcontainers.mariadb.MariaDBContainer;
import java.math.BigDecimal;
import com.oopsw.security.JwtTestKeys;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(properties = {"eureka.client.enabled=false", "spring.cloud.discovery.enabled=false",
    "test.inventory.legacy=true"})
@Import(TestcontainersConfiguration.class)
class InventoryMigrationCompatibilityTest {
    @DynamicPropertySource
    static void keys(DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
    }
    @Autowired InventoryService inventory;
    @Autowired @Qualifier("inventoryDataSource") DataSource dataSource;
    @Autowired JdbcTemplate catalog;
    @Autowired @Qualifier("mariaDBContainer") MariaDBContainer catalogContainer;
    @Autowired @Qualifier("inventoryDatabase") MariaDBContainer inventoryContainer;

    @Test
    void 독립_과거_V1의_Flyway이력과_카탈로그를_보존한다() {
        var stock = new JdbcTemplate(dataSource);
        assertEquals(LegacyMigrationFixture.originalHistory(catalogContainer),
            catalog.queryForList("SELECT * FROM flyway_schema_history WHERE version='1'"));
        assertEquals(LegacyMigrationFixture.originalHistory(inventoryContainer),
            stock.queryForList("SELECT * FROM flyway_schema_history WHERE version='1'"));
        assertEquals(2, catalog.queryForObject("SELECT COUNT(*) FROM flyway_schema_history WHERE success=1", Integer.class));
        var item = catalog.queryForMap("SELECT * FROM item WHERE id=777");
        assertEquals(101L, ((Number)item.get("account_id")).longValue());
        assertEquals("LEGACY-777", item.get("sku"));
        assertEquals("legacy material", item.get("name"));
        assertEquals("preserve me", item.get("description"));
        assertEquals(new BigDecimal("1250.50"), item.get("unit_price"));
        assertEquals("ACTIVE", item.get("status"));
        assertEquals(4L, ((Number)item.get("version")).longValue());
        assertEquals("2020-01-01 00:00:00.0", item.get("created_at").toString());
        assertEquals("2020-01-02 00:00:00.0", item.get("updated_at").toString());
        assertEquals(1, catalog.queryForObject("SELECT COUNT(*) FROM item", Integer.class));
        assertEquals(88L, stock.queryForObject("SELECT id FROM stock_movement WHERE request_id='INITIAL-77'", Long.class));
        assertEquals(42L, stock.queryForObject("SELECT quantity_after FROM stock_movement WHERE id=88", Long.class));
    }

    @Test
    void 기존_재고DB의_수량_버전_원장과_Flyway이력이_보존된다() {
        var result=inventory.get(101L,777L);
        assertEquals(77L,result.inventoryId());
        assertEquals(777L,result.foodMaterialId());
        assertEquals(42L,result.onHandQuantity());
        assertEquals(3L,result.version());
        assertEquals(1L,inventory.movements(101L,777L,0,20).totalElements());
        var stock=new JdbcTemplate(dataSource);
        assertEquals(2,stock.queryForObject("SELECT COUNT(*) FROM flyway_schema_history WHERE success=1",Integer.class));
        assertEquals(0,catalog.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='inventory'",Integer.class));
        assertEquals(0,stock.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='item'",Integer.class));
    }
}
