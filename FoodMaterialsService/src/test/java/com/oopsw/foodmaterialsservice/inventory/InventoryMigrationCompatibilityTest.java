package com.oopsw.foodmaterialsservice.inventory;

import static org.junit.jupiter.api.Assertions.assertEquals;
import com.oopsw.foodmaterialsservice.inventory.service.InventoryService;
import com.oopsw.foodmaterialsservice.support.TestcontainersConfiguration;
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
