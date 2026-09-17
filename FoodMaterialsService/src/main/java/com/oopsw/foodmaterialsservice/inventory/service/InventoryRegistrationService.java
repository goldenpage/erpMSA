package com.oopsw.foodmaterialsservice.inventory.service;

import com.oopsw.foodmaterialsservice.service.FoodMaterialsService;
import com.oopsw.foodmaterialsservice.inventory.web.dto.CreateInventoryRequest;
import com.oopsw.foodmaterialsservice.inventory.web.dto.InventoryResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class InventoryRegistrationService {
    private final FoodMaterialsService foodMaterialsService;
    private final InventoryService inventoryService;

    public InventoryResponse create(Long accountId, CreateInventoryRequest request) {
        // Catalog records cannot be hard-deleted or transferred through the current API.
        foodMaterialsService.get(accountId, request.foodMaterialId());
        return inventoryService.create(accountId, request.foodMaterialId(), request.initialQuantity());
    }
}
