package com.oopsw.accountservice.advice;

import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiErrorResponse;
import com.oopsw.accountservice.api.ApiException;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
public class ApiExceptionHandler {

    static final String AUTH_BUSY_RETRY_AFTER_SECONDS = "1";

    private static final Logger log = LoggerFactory.getLogger(
        ApiExceptionHandler.class
    );

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ApiErrorResponse> handleApiException(
        ApiException exception,
        HttpServletRequest request
    ) {
        return response(exception.errorCode(), request, exception.retryAfterSeconds());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiErrorResponse> handleValidation(
        MethodArgumentNotValidException exception,
        HttpServletRequest request
    ) {
        List<ApiErrorResponse.FieldViolation> fieldErrors = exception
            .getBindingResult()
            .getFieldErrors()
            .stream()
            .map(error -> new ApiErrorResponse.FieldViolation(
                error.getField(),
                Objects.requireNonNullElse(
                    error.getDefaultMessage(),
                    "올바르지 않은 값입니다."
                )
            ))
            .distinct()
            .sorted(Comparator.comparing(
                ApiErrorResponse.FieldViolation::field
            ))
            .toList();

        ApiErrorCode errorCode = ApiErrorCode.INVALID_REQUEST;
        return ResponseEntity.status(errorCode.status())
            .body(ApiErrorResponse.of(
                errorCode,
                request.getRequestURI(),
                fieldErrors
            ));
    }

    @ExceptionHandler({
        HandlerMethodValidationException.class
    })
    public ResponseEntity<ApiErrorResponse> handleMethodValidation(
        HandlerMethodValidationException exception,
        HttpServletRequest request
    ) {
        return response(ApiErrorCode.INVALID_REQUEST, request);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiErrorResponse> handleMalformedRequest(
        HttpMessageNotReadableException exception,
        HttpServletRequest request
    ) {
        return response(ApiErrorCode.MALFORMED_REQUEST, request);
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<ApiErrorResponse> handleDataConflict(
        DataIntegrityViolationException exception,
        HttpServletRequest request
    ) {
        return response(ApiErrorCode.ACCOUNT_CONFLICT, request);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiErrorResponse> handleNotFound(
        NoResourceFoundException exception,
        HttpServletRequest request
    ) {
        return response(ApiErrorCode.RESOURCE_NOT_FOUND, request);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiErrorResponse> handleMethodNotAllowed(
        HttpRequestMethodNotSupportedException exception,
        HttpServletRequest request
    ) {
        return response(ApiErrorCode.METHOD_NOT_ALLOWED, request);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiErrorResponse> handleUnexpectedException(
        Exception exception,
        HttpServletRequest request
    ) {
        log.error(
            "처리되지 않은 API 예외가 발생했습니다. path={}",
            request.getRequestURI(),
            exception
        );
        return response(ApiErrorCode.INTERNAL_SERVER_ERROR, request);
    }

    private ResponseEntity<ApiErrorResponse> response(
        ApiErrorCode errorCode,
        HttpServletRequest request
    ) {
        return response(errorCode, request, null);
    }

    private ResponseEntity<ApiErrorResponse> response(
        ApiErrorCode errorCode,
        HttpServletRequest request,
        Long retryAfterSeconds
    ) {
        ResponseEntity.BodyBuilder builder = ResponseEntity.status(errorCode.status());
        if (retryAfterSeconds != null) {
            builder.header(HttpHeaders.RETRY_AFTER, String.valueOf(Math.max(1, retryAfterSeconds)));
        } else if (errorCode == ApiErrorCode.AUTH_BUSY) {
            // 과부하 거절은 일시적이다. 클라이언트가 즉시 재시도하지 않도록 대기 시간을 알려 준다.
            builder.header(HttpHeaders.RETRY_AFTER, AUTH_BUSY_RETRY_AFTER_SECONDS);
        }
        return builder
            .body(ApiErrorResponse.of(
                errorCode,
                request.getRequestURI()
            ));
    }
}
