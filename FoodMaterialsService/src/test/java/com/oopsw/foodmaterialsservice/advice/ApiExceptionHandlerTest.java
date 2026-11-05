package com.oopsw.foodmaterialsservice.advice;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.foodmaterialsservice.api.ApiErrorCode;
import com.oopsw.foodmaterialsservice.api.ApiException;
import jakarta.validation.ConstraintViolationException;
import jakarta.validation.Valid;
import jakarta.validation.Validation;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@org.junit.jupiter.api.Tag("unit")
class ApiExceptionHandlerTest {

    private record Paging(@Min(0) int page, @Min(1) @Max(100) int size) {}
    private record Query(@Valid Paging query) {}

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void 제약_위반을_400과_정렬된_필드_오류로_변환한다() {
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var violations = factory.getValidator().validate(new Query(new Paging(-1, 101)));
            assertThat(violations).hasSize(2);
            var response = handler.handleConstraintViolation(
                new ConstraintViolationException(violations),
                new MockHttpServletRequest("GET", "/foodmaterials")
            );
            assertThat(response.getStatusCode().value()).isEqualTo(400);
            assertThat(response.getBody().code()).isEqualTo("INVALID_REQUEST");
            assertThat(response.getBody().path()).isEqualTo("/foodmaterials");
            assertThat(response.getBody().fieldErrors())
                .extracting(error -> error.field()).containsExactly("page", "size");
            assertThat(response.getBody().fieldErrors())
                .allSatisfy(error -> assertThat(error.message()).isNotBlank());
        }
    }

    @Test
    void 일반_서버_예외는_500을_유지한다() {
        var response = handler.handleUnexpectedException(
            new IllegalStateException("test failure"),
            new MockHttpServletRequest("GET", "/foodmaterials")
        );
        assertThat(response.getStatusCode().value()).isEqualTo(500);
        assertThat(response.getBody().code()).isEqualTo("INTERNAL_SERVER_ERROR");
    }

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
