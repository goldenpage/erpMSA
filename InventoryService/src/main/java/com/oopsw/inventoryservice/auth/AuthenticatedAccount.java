package com.oopsw.inventoryservice.auth;

public record AuthenticatedAccount(
    Long accountId,
    String email,
    String role
) {
}
