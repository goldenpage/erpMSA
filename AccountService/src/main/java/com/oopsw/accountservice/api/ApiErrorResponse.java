package com.oopsw.accountservice.api;

import java.time.Instant;
import java.util.List;

public record ApiErrorResponse(
    String timestamp,
    int status,
    String code,
    String message,
    String path,
    List<FieldViolation> fieldErrors
) {
    public ApiErrorResponse {
        fieldErrors = List.copyOf(fieldErrors);
    }

    public static ApiErrorResponse of(
        ApiErrorCode errorCode,
        String path
    ) {
        return of(errorCode, path, List.of());
    }

    public static ApiErrorResponse of(
        ApiErrorCode errorCode,
        String path,
        List<FieldViolation> fieldErrors
    ) {
        return new ApiErrorResponse(
            Instant.now().toString(),
            errorCode.status().value(),
            errorCode.name(),
            errorCode.message(),
            path,
            fieldErrors
        );
    }

    public record FieldViolation(
        String field,
        String message
    ) {
    }
}
