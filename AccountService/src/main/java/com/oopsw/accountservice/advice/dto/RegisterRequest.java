package com.oopsw.accountservice.advice.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;


public record RegisterRequest(

    @NotBlank
    @Email
    @Size(max = 255)
    String email,

    @NotBlank
    @Pattern(regexp = "\\d{10}")
    String businessId,

    @NotBlank
    @Size(min = 8, max = 100)
    String password,

    @NotBlank
    @Size(max = 50)
    String name,

    @Size(max = 20)
    String phone,

    @NotBlank
    @Size(max = 100)
    String storeName,

    @Size(max = 50)
    String storeType,

    @Size(max = 50)
    String storeCategory,

    boolean marketingAgreed
) {
}