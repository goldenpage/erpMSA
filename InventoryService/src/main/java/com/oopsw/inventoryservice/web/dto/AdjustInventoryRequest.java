package com.oopsw.inventoryservice.web.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

public record AdjustInventoryRequest(
    @NotBlank
    @Size(max = 64)
    @Pattern(regexp = "[A-Za-z0-9][A-Za-z0-9._:-]*")
    String requestId,

    @NotNull
    @Min(-1_000_000_000L)
    @Max(1_000_000_000L)
    Long quantityDelta,

    @NotBlank
    @Size(max = 255)
    String reason,

    @NotNull
    @PositiveOrZero
    Long version
) {
}
