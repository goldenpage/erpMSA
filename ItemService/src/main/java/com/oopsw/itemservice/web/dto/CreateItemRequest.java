package com.oopsw.itemservice.web.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

public record CreateItemRequest(
    @NotBlank
    @Size(max = 64)
    @Pattern(regexp = "[A-Za-z0-9][A-Za-z0-9._-]*")
    String sku,

    @NotBlank
    @Size(max = 100)
    String name,

    @Size(max = 1000)
    String description,

    @NotNull
    @DecimalMin("0.00")
    @Digits(integer = 13, fraction = 2)
    BigDecimal unitPrice
) {
}
