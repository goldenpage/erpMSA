package com.oopsw.accountservice.advice;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.oopsw.accountservice.api.ApiErrorCode;
import com.oopsw.accountservice.api.ApiErrorResponse;
import com.oopsw.accountservice.api.ApiException;
import java.util.Objects;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.validation.BeanPropertyBindingResult;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;

@org.junit.jupiter.api.Tag("unit")
class ApiExceptionHandlerTest {

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void 도메인_예외를_표준_오류_응답으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "POST",
            "/account/auth/login"
        );

        ResponseEntity<ApiErrorResponse> response =
            handler.handleApiException(
                new ApiException(ApiErrorCode.INVALID_CREDENTIALS),
                request
            );

        ApiErrorResponse body = Objects.requireNonNull(response.getBody());
        assertThat(response.getStatusCode().value()).isEqualTo(401);
        assertThat(body.status()).isEqualTo(401);
        assertThat(body.code()).isEqualTo("INVALID_CREDENTIALS");
        assertThat(body.path()).isEqualTo("/account/auth/login");
        assertThat(body.timestamp()).isNotBlank();
        assertThat(body.fieldErrors()).isEmpty();
    }

    @Test
    void 인증_과부하_거절에는_재시도_대기_시간을_알린다() {
        ResponseEntity<ApiErrorResponse> response = handler.handleApiException(
            new ApiException(ApiErrorCode.AUTH_BUSY),
            new MockHttpServletRequest("POST", "/account/auth/login")
        );

        assertThat(response.getStatusCode().value()).isEqualTo(503);
        assertThat(response.getHeaders().getFirst("Retry-After")).isEqualTo("1");
        assertThat(Objects.requireNonNull(response.getBody()).code()).isEqualTo("AUTH_BUSY");
        assertThat(handler.handleApiException(new ApiException(ApiErrorCode.INVALID_CREDENTIALS),
            new MockHttpServletRequest("POST", "/account/auth/login")).getHeaders().getFirst("Retry-After")).isNull();
    }

    @Test
    void 시도_제한_거절에는_남은_시간을_Retry_After로_알린다() {
        ResponseEntity<ApiErrorResponse> response = handler.handleApiException(
            new ApiException(ApiErrorCode.LOGIN_RATE_LIMITED, 37L),
            new MockHttpServletRequest("POST", "/account/auth/login")
        );

        assertThat(response.getStatusCode().value()).isEqualTo(429);
        assertThat(response.getHeaders().getFirst("Retry-After")).isEqualTo("37");
        assertThat(Objects.requireNonNull(response.getBody()).code()).isEqualTo("LOGIN_RATE_LIMITED");
    }

    @Test
    void 검증_예외에는_필드명과_메시지만_포함한다() {
        Object target = new Object();
        BeanPropertyBindingResult bindingResult =
            new BeanPropertyBindingResult(target, "registerRequest");
        bindingResult.addError(new FieldError(
            "registerRequest",
            "email",
            "user-secret@example.com",
            false,
            null,
            null,
            "올바른 이메일 형식이어야 합니다."
        ));

        MethodArgumentNotValidException exception =
            new MethodArgumentNotValidException(
                mock(MethodParameter.class),
                bindingResult
            );
        MockHttpServletRequest request = new MockHttpServletRequest(
            "POST",
            "/account/auth/register"
        );

        ResponseEntity<ApiErrorResponse> response =
            handler.handleValidation(exception, request);

        ApiErrorResponse body = Objects.requireNonNull(response.getBody());
        assertThat(response.getStatusCode().value()).isEqualTo(400);
        assertThat(body.code()).isEqualTo("INVALID_REQUEST");
        assertThat(body.fieldErrors()).containsExactly(
            new ApiErrorResponse.FieldViolation(
                "email",
                "올바른 이메일 형식이어야 합니다."
            )
        );
        assertThat(body.toString())
            .doesNotContain("user-secret@example.com");
    }
}
