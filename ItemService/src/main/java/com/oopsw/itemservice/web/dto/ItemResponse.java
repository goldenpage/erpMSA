package com.oopsw.itemservice.web.dto;

import com.oopsw.itemservice.domain.ItemEntity;
import com.oopsw.itemservice.domain.ItemStatus;
import java.math.BigDecimal;
import java.time.Instant;

public record ItemResponse(
    Long itemId,
    String sku,
    String name,
    String description,
    BigDecimal unitPrice,
    ItemStatus status,
    Long version,
    Instant createdAt,
    Instant updatedAt
) {
    public static ItemResponse from(ItemEntity item) {
        return new ItemResponse(
            item.getId(),
            item.getSku(),
            item.getName(),
            item.getDescription(),
            item.getUnitPrice(),
            item.getStatus(),
            item.getVersion(),
            item.getCreatedAt(),
            item.getUpdatedAt()
        );
    }
}
