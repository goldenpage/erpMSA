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
