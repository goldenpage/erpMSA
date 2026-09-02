package com.oopsw.inventoryservice.web.dto;

import com.oopsw.inventoryservice.domain.MovementType;
import com.oopsw.inventoryservice.domain.StockMovementEntity;
import java.time.Instant;

public record StockMovementResponse(
    Long movementId,
    Long itemId,
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
            movement.getItemId(),
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
