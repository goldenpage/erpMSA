package com.oopsw.inventoryservice.web.dto;

import com.oopsw.inventoryservice.domain.InventoryEntity;
import java.time.Instant;

public record InventoryResponse(
    Long inventoryId,
    Long itemId,
    Long onHandQuantity,
    Long version,
    Instant createdAt,
    Instant updatedAt
) {
    public static InventoryResponse from(InventoryEntity inventory) {
        return new InventoryResponse(
            inventory.getId(),
            inventory.getItemId(),
            inventory.getOnHandQuantity(),
            inventory.getVersion(),
            inventory.getCreatedAt(),
            inventory.getUpdatedAt()
        );
    }
}
