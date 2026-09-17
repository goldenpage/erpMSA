package com.oopsw.foodmaterialsservice.inventory.web.dto;

import com.oopsw.foodmaterialsservice.inventory.domain.MovementType;
import com.oopsw.foodmaterialsservice.inventory.domain.StockMovementEntity;
import java.time.Instant;

public record StockMovementResponse(
    Long movementId,
    Long foodMaterialId,
    String requestId,
    MovementType movementType,
    Long quantityDelta,
    Long quantityBefore,
    Long quantityAfter,
    String reason,
    Instant createdAt
) {
    public static StockMovementResponse from(StockMovementEntity movement) {
        return new StockMovementResponse(
            movement.getId(),
            movement.getFoodMaterialId(),
            movement.getRequestId(),
            movement.getMovementType(),
            movement.getQuantityDelta(),
            movement.getQuantityBefore(),
            movement.getQuantityAfter(),
            movement.getReason(),
            movement.getCreatedAt()
        );
    }
}
