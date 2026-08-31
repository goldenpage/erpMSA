package com.oopsw.gatewayserver.api;

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
    public static ApiErrorResponse of(
        ApiErrorCode errorCode,
        String path
    ) {
        return new ApiErrorResponse(
            Instant.now().toString(),
            errorCode.status().value(),
            errorCode.name(),
            errorCode.message(),
            path,
            List.of()
        );
    }

    public record FieldViolation(
        String field,
        String message
    ) {
    }
}
