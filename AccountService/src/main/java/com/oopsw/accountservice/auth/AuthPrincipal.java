package com.oopsw.accountservice.auth;

public record AuthPrincipal(Long accountId,
                            String email) {

}
