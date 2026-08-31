package com.oopsw.accountservice.api;

import org.springframework.http.HttpStatus;

public enum ApiErrorCode {
    INVALID_REQUEST(
        HttpStatus.BAD_REQUEST,
        "요청 값이 올바르지 않습니다."
    ),
    MALFORMED_REQUEST(
        HttpStatus.BAD_REQUEST,
        "요청 본문을 읽을 수 없습니다."
    ),
    EMAIL_ALREADY_EXISTS(
        HttpStatus.CONFLICT,
        "이미 가입된 이메일입니다."
    ),
    BUSINESS_ID_ALREADY_EXISTS(
        HttpStatus.CONFLICT,
        "이미 등록된 사업자번호입니다."
    ),
    ACCOUNT_CONFLICT(
        HttpStatus.CONFLICT,
        "이미 등록된 계정 정보입니다."
    ),
    INVALID_CREDENTIALS(
        HttpStatus.UNAUTHORIZED,
        "이메일 또는 비밀번호가 올바르지 않습니다."
    ),
    ACCOUNT_LOGIN_FORBIDDEN(
        HttpStatus.FORBIDDEN,
        "로그인할 수 없는 계정 상태입니다."
    ),
    INVALID_REFRESH_TOKEN(
        HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Refresh Token입니다."
    ),
    AUTHENTICATION_REQUIRED(
        HttpStatus.UNAUTHORIZED,
        "Access Token이 필요합니다."
    ),
    INVALID_ACCESS_TOKEN(
        HttpStatus.UNAUTHORIZED,
        "유효하지 않은 Access Token입니다."
    ),
    ACCESS_DENIED(
        HttpStatus.FORBIDDEN,
        "접근 권한이 없습니다."
    ),
    RESOURCE_NOT_FOUND(
        HttpStatus.NOT_FOUND,
        "요청한 리소스를 찾을 수 없습니다."
    ),
    METHOD_NOT_ALLOWED(
        HttpStatus.METHOD_NOT_ALLOWED,
        "지원하지 않는 HTTP 메서드입니다."
    ),
    INTERNAL_SERVER_ERROR(
        HttpStatus.INTERNAL_SERVER_ERROR,
        "서버 내부 오류가 발생했습니다."
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
