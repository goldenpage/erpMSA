package com.oopsw.foodmaterialsservice.inventory.web.dto;
import jakarta.validation.constraints.*;
public record DisposeInventoryRequest(
    @NotBlank @Size(max=64) @Pattern(regexp="DISPOSAL-[0-9a-fA-F-]{36}") String requestId,
    @NotNull @Positive Long quantity,
    @NotBlank @Size(max=255) String reason
) {}
