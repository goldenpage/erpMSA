package com.oopsw.inventoryservice.api;

import org.springframework.http.HttpStatus;

public enum ApiErrorCode {
    INVALID_REQUEST(HttpStatus.BAD_REQUEST, "요청 값이 올바르지 않습니다."),
    MALFORMED_REQUEST(HttpStatus.BAD_REQUEST, "요청 본문을 읽을 수 없습니다."),
    AUTHENTICATION_REQUIRED(HttpStatus.UNAUTHORIZED, "Access Token이 필요합니다."),
    INVALID_ACCESS_TOKEN(HttpStatus.UNAUTHORIZED, "유효하지 않은 Access Token입니다."),
    ITEM_NOT_FOUND(HttpStatus.NOT_FOUND, "품목을 찾을 수 없습니다."),
    INVENTORY_NOT_FOUND(HttpStatus.NOT_FOUND, "재고를 찾을 수 없습니다."),
    INVENTORY_ALREADY_EXISTS(HttpStatus.CONFLICT, "이미 생성된 품목 재고입니다."),
    ADJUSTMENT_ALREADY_EXISTS(HttpStatus.CONFLICT, "이미 처리된 재고 변경 요청입니다."),
    INSUFFICIENT_STOCK(HttpStatus.CONFLICT, "재고 수량이 부족합니다."),
    INVENTORY_CONFLICT(HttpStatus.CONFLICT, "재고 정보가 다른 요청에 의해 변경되었습니다."),
    ITEM_SERVICE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "품목 서비스에 연결할 수 없습니다."),
    RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND, "요청한 리소스를 찾을 수 없습니다."),
    METHOD_NOT_ALLOWED(HttpStatus.METHOD_NOT_ALLOWED, "지원하지 않는 HTTP 메서드입니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 내부 오류가 발생했습니다.");

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
