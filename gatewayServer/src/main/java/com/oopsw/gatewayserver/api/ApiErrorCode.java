package com.oopsw.gatewayserver.api;

import org.springframework.http.HttpStatus;

public enum ApiErrorCode {
    AUTHENTICATION_REQUIRED(
        HttpStatus.UNAUTHORIZED,
        "Access Token이 필요합니다."
    ),
    INVALID_ACCESS_TOKEN(
        HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Access Token입니다."
    ),
    ROUTE_BUSY(
        HttpStatus.SERVICE_UNAVAILABLE,
        "요청이 많아 처리할 수 없습니다. 잠시 후 다시 시도하세요."
    );

    private final HttpStatus status;
    private final String message;

    ApiErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    public HttpStatus status() {
        return status;
    }

    public String message() {
        return message;
    }
}
