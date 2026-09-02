package com.oopsw.inventoryservice.advice;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class ApiExceptionHandlerTest {

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void 도메인_예외를_표준_응답으로_변환한다() {
        MockHttpServletRequest request = new MockHttpServletRequest(
            "GET",
            "/inventories/100"
        );

        var response = handler.handleApiException(
            new ApiException(ApiErrorCode.INVENTORY_NOT_FOUND),
            request
        );

        assertThat(response.getStatusCode().value()).isEqualTo(404);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code())
            .isEqualTo("INVENTORY_NOT_FOUND");
        assertThat(response.getBody().path())
            .isEqualTo("/inventories/100");
    }
}
