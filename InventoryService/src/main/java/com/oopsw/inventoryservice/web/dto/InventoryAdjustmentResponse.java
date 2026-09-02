package com.oopsw.inventoryservice.web.dto;

public record InventoryAdjustmentResponse(
    InventoryResponse inventory,
    StockMovementResponse movement
) {
}
