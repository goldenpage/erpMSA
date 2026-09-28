package com.oopsw.foodmaterialsservice.support;

import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.flywaydb.core.Flyway;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.mariadb.MariaDBContainer;

/** Independent V1 blobs from Git 788e59d; never uses the current migration to seed history. */
public final class LegacyMigrationFixture {
    private static final Map<String, List<Map<String, Object>>> HISTORY = new ConcurrentHashMap<>();
    private LegacyMigrationFixture() {}

    public static void prepare(MariaDBContainer database, String kind) {
        String filename = switch (kind) {
            case "catalog" -> "V1__create_item_schema.sql";
            case "inventory" -> "V1__create_inventory_schema.sql";
            default -> throw new IllegalArgumentException("Unknown legacy fixture");
        };
        String expected = kind.equals("catalog")
            ? "bb9d01d0b2f12139e109edcfdef767e67a0c9d665803febbbc956ac343e82878"
            : "b4e0bc37f561c722251d30bd1bb7f7da12037b93c54607cf958639ffa1dc3c7e";
        String location = "legacy-migrations/" + kind;
        try (var input = LegacyMigrationFixture.class.getClassLoader().getResourceAsStream(location + "/" + filename)) {
            if (input == null || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(input.readAllBytes())).equals(expected)) {
                throw new IllegalStateException("Historical V1 fixture checksum changed");
            }
        } catch (Exception exception) {
            throw new IllegalStateException("Cannot verify historical V1 fixture", exception);
        }
        Flyway.configure().dataSource(database.getJdbcUrl(), database.getUsername(), database.getPassword())
            .locations("classpath:" + location).target("1").baselineOnMigrate(false).cleanDisabled(true).load().migrate();
        var jdbc = new JdbcTemplate(new DriverManagerDataSource(database.getJdbcUrl(), database.getUsername(), database.getPassword()));
        HISTORY.put(database.getJdbcUrl(), jdbc.queryForList("SELECT * FROM flyway_schema_history WHERE version='1'"));
        if (kind.equals("catalog")) {
            jdbc.update("INSERT INTO item (id,account_id,sku,name,description,unit_price,status,version,created_at,updated_at) VALUES (777,101,'LEGACY-777','legacy material','preserve me',1250.50,'ACTIVE',4,'2020-01-01 00:00:00','2020-01-02 00:00:00')");
        } else {
            jdbc.update("INSERT INTO inventory (id,account_id,item_id,on_hand_quantity,version,created_at,updated_at) VALUES (77,101,777,42,3,'2020-01-01 00:00:00','2020-01-02 00:00:00')");
            jdbc.update("INSERT INTO stock_movement (id,inventory_id,account_id,item_id,request_id,movement_type,quantity_delta,quantity_before,quantity_after,reason,created_at) VALUES (88,77,101,777,'INITIAL-77','INITIAL',42,0,42,'legacy','2020-01-01 00:00:00')");
        }
    }

    public static List<Map<String, Object>> originalHistory(MariaDBContainer database) {
        return HISTORY.get(database.getJdbcUrl());
    }
}
