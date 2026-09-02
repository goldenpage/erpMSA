package com.oopsw.inventoryservice.web.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;

public record CreateInventoryRequest(
    @NotNull
    @Positive
    Long itemId,

    @NotNull
    @PositiveOrZero
    Long initialQuantity
) {
}
