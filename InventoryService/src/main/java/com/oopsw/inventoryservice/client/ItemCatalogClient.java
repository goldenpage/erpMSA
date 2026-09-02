package com.oopsw.inventoryservice.client;

public interface ItemCatalogClient {

    void verifyOwnedItem(Long itemId, String authorization);
}
