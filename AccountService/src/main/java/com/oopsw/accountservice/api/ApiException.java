package com.oopsw.accountservice.api;

public final class ApiException extends RuntimeException {

    private final ApiErrorCode errorCode;
    private final Long retryAfterSeconds;

    public ApiException(ApiErrorCode errorCode) {
        this(errorCode, null);
    }

    /** 일시적인 거절(시도 제한 등)에서 클라이언트가 다시 시도할 수 있는 시점까지의 초. 응답의 Retry-After가 된다. */
    public ApiException(ApiErrorCode errorCode, Long retryAfterSeconds) {
        super(errorCode.message());
        this.errorCode = errorCode;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public ApiErrorCode errorCode() {
        return errorCode;
    }

    public Long retryAfterSeconds() {
        return retryAfterSeconds;
    }
}
