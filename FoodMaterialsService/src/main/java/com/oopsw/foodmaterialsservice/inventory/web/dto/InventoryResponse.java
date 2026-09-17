package com.oopsw.foodmaterialsservice.inventory.web.dto;

import com.oopsw.foodmaterialsservice.inventory.domain.InventoryEntity;
import java.time.Instant;

public record InventoryResponse(
    Long inventoryId,
    Long foodMaterialId,
    Long onHandQuantity,
    Long version,
    Instant createdAt,
    Instant updatedAt
) {
    public static InventoryResponse from(InventoryEntity inventory) {
        return new InventoryResponse(
            inventory.getId(),
            inventory.getFoodMaterialId(),
            inventory.getOnHandQuantity(),
            inventory.getVersion(),
            inventory.getCreatedAt(),
            inventory.getUpdatedAt()
        );
    }
}
