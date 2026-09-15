package com.oopsw.foodmaterialsservice.auth;

public record AuthenticatedAccount(
    Long accountId,
    String email,
    String role
) {
}
