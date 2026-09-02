package com.oopsw.inventoryservice.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

import com.oopsw.inventoryservice.client.ItemCatalogClient;
import com.oopsw.inventoryservice.web.dto.CreateInventoryRequest;
import com.oopsw.inventoryservice.web.dto.InventoryResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class InventoryRegistrationServiceTest {

    @Mock
    private ItemCatalogClient itemCatalogClient;

    @Mock
    private InventoryService inventoryService;

    @InjectMocks
    private InventoryRegistrationService registrationService;

    @Test
    void 품목소유권을_먼저_검증한_뒤_재고를_생성한다() {
        CreateInventoryRequest request = new CreateInventoryRequest(100L, 30L);
        InventoryResponse expected = new InventoryResponse(
            1L,
            100L,
            30L,
            0L,
            null,
            null
        );
        when(inventoryService.create(10L, 100L, 30L)).thenReturn(expected);

        var response = registrationService.create(
            10L,
            "Bearer token",
            request
        );

        var ordered = inOrder(itemCatalogClient, inventoryService);
        ordered.verify(itemCatalogClient).verifyOwnedItem(
            100L,
            "Bearer token"
        );
        ordered.verify(inventoryService).create(10L, 100L, 30L);
        assertThat(response).isEqualTo(expected);
    }
}
