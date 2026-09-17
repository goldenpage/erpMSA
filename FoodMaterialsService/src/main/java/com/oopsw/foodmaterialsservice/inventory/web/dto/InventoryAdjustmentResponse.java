package com.oopsw.foodmaterialsservice.inventory.web.dto;

public record InventoryAdjustmentResponse(
    InventoryResponse inventory,
    StockMovementResponse movement
) {
}
