package com.oopsw.inventoryservice.service;

import com.oopsw.inventoryservice.client.FoodMaterialCatalogClient;
import com.oopsw.inventoryservice.web.dto.CreateInventoryRequest;
import com.oopsw.inventoryservice.web.dto.InventoryResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class InventoryRegistrationService {

    private final FoodMaterialCatalogClient itemCatalogClient;
    private final InventoryService inventoryService;

    public InventoryResponse create(
        Long accountId,
        String authorization,
        CreateInventoryRequest request
    ) {
        itemCatalogClient.verifyOwnedFoodMaterial(request.itemId(), authorization);
        return inventoryService.create(
            accountId,
            request.itemId(),
            request.initialQuantity()
        );
    }
}
