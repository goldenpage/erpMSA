package com.oopsw.inventoryservice.client;

public interface FoodMaterialCatalogClient {

    void verifyOwnedFoodMaterial(Long itemId, String authorization);
}
