package com.oopsw.foodmaterialsservice.web.dto;

import com.oopsw.foodmaterialsservice.domain.FoodMaterialEntity;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialStatus;
import java.math.BigDecimal;
import java.time.Instant;

public record FoodMaterialResponse(
    Long foodMaterialId,
    String sku,
    String name,
    String description,
    BigDecimal unitPrice,
    FoodMaterialStatus status,
    Long version,
    Instant createdAt,
    Instant updatedAt
) {
    public static FoodMaterialResponse from(FoodMaterialEntity item) {
        return new FoodMaterialResponse(
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
