package com.oopsw.itemservice.auth;

public record AuthenticatedAccount(
    Long accountId,
    String email,
    String role
) {
}
