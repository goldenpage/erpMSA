package com.oopsw.foodmaterialsservice.advice;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.foodmaterialsservice.api.ApiErrorCode;
import com.oopsw.foodmaterialsservice.api.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

class ApiExceptionHandlerTest {

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void 도메인_예외를_표준_응답으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/foodmaterials/99"
        );

        var response = handler.handleApiException(
            new ApiException(ApiErrorCode.FOOD_MATERIAL_NOT_FOUND),
            request
        );

        assertThat(response.getStatusCode().value()).isEqualTo(404);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("FOOD_MATERIAL_NOT_FOUND");
        assertThat(response.getBody().path()).isEqualTo("/foodmaterials/99");
        assertThat(response.getBody().fieldErrors()).isEmpty();
    }

    @Test
    void 잘못된_쿼리_타입은_400으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/foodmaterials"
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
