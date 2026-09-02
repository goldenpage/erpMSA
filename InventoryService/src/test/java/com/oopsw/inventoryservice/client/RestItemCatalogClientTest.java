package com.oopsw.inventoryservice.client;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withResourceNotFound;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class RestItemCatalogClientTest {

    private MockRestServiceServer server;
    private RestItemCatalogClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new RestItemCatalogClient(builder, "http://ITEMSERVICE");
    }

    @Test
    void 소유한_품목이면_검증을_통과한다() {
        server.expect(requestTo("http://ITEMSERVICE/items/100"))
            .andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer token"))
            .andRespond(withSuccess());

        assertThatCode(() -> client.verifyOwnedItem(100L, "Bearer token"))
            .doesNotThrowAnyException();
        server.verify();
    }

    @Test
    void 품목이_없으면_표준_도메인예외로_변환한다() {
        server.expect(requestTo("http://ITEMSERVICE/items/999"))
            .andRespond(withResourceNotFound());

        assertThatThrownBy(() -> client.verifyOwnedItem(999L, "Bearer token"))
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(ApiErrorCode.ITEM_NOT_FOUND);
        server.verify();
    }

    @Test
    void 품목서비스_장애는_503_도메인예외로_변환한다() {
        server.expect(requestTo("http://ITEMSERVICE/items/100"))
            .andRespond(withServerError());

        assertThatThrownBy(() -> client.verifyOwnedItem(100L, "Bearer token"))
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(ApiErrorCode.ITEM_SERVICE_UNAVAILABLE);
        server.verify();
    }
}
