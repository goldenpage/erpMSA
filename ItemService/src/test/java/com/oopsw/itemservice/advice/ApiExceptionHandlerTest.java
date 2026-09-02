package com.oopsw.itemservice.advice;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.itemservice.api.ApiErrorCode;
import com.oopsw.itemservice.api.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

class ApiExceptionHandlerTest {

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void 도메인_예외를_표준_응답으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/items/99"
        );

        var response = handler.handleApiException(
            new ApiException(ApiErrorCode.ITEM_NOT_FOUND),
            request
        );

        assertThat(response.getStatusCode().value()).isEqualTo(404);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("ITEM_NOT_FOUND");
        assertThat(response.getBody().path()).isEqualTo("/items/99");
        assertThat(response.getBody().fieldErrors()).isEmpty();
    }

    @Test
    void 잘못된_쿼리_타입은_400으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/items"
        );
        MethodArgumentTypeMismatchException exception =
            new MethodArgumentTypeMismatchException(
                "UNKNOWN",
                Enum.class,
                "status",
                null,
                new IllegalArgumentException()
            );

        var response = handler.handleTypeMismatch(exception, request);

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("INVALID_REQUEST");
    }
}
