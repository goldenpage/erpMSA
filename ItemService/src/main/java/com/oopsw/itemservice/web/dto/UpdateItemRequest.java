package com.oopsw.itemservice.web.dto;

import com.oopsw.itemservice.domain.ItemStatus;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

public record UpdateItemRequest(
    @NotBlank
    @Size(max = 100)
    String name,

    @Size(max = 1000)
    String description,

    @NotNull
    @DecimalMin("0.00")
    @Digits(integer = 13, fraction = 2)
    BigDecimal unitPrice,

    @NotNull
    ItemStatus status,

    @NotNull
    @PositiveOrZero
    Long version
) {
}
