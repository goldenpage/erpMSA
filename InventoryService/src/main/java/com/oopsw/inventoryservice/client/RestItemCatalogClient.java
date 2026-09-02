package com.oopsw.inventoryservice.client;

import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class RestItemCatalogClient implements ItemCatalogClient {

    private static final Logger log = LoggerFactory.getLogger(
        RestItemCatalogClient.class
    );

    private final RestClient restClient;

    public RestItemCatalogClient(
        @LoadBalanced RestClient.Builder builder,
        @Value("${app.item-service.base-url}") String baseUrl
    ) {
        this.restClient = builder.baseUrl(baseUrl).build();
    }

    @Override
    public void verifyOwnedItem(Long itemId, String authorization) {
        try {
            restClient.get()
                .uri("/items/{itemId}", itemId)
                .header(HttpHeaders.AUTHORIZATION, authorization)
                .exchange((request, response) -> {
                    int status = response.getStatusCode().value();

                    if (response.getStatusCode().is2xxSuccessful()) {
                        return null;
                    }
                    if (status == 404) {
                        throw new ApiException(ApiErrorCode.ITEM_NOT_FOUND);
                    }
                    if (status == 401 || status == 403) {
                        throw new ApiException(
                            ApiErrorCode.INVALID_ACCESS_TOKEN
                        );
                    }
                    throw new ApiException(
                        ApiErrorCode.ITEM_SERVICE_UNAVAILABLE
                    );
                });
        } catch (ApiException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            log.warn("ItemService 품목 검증 호출에 실패했습니다. itemId={}", itemId);
            throw new ApiException(ApiErrorCode.ITEM_SERVICE_UNAVAILABLE);
        }
    }
}
