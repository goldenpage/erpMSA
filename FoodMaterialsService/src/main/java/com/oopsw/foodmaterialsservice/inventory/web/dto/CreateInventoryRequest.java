package com.oopsw.foodmaterialsservice.inventory.web.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;

public record CreateInventoryRequest(
    @NotNull
    @Positive
    Long foodMaterialId,

    @NotNull
    @PositiveOrZero
    Long initialQuantity
) {
}
