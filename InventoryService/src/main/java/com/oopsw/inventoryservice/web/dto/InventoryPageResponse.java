package com.oopsw.inventoryservice.web.dto;

import java.util.List;
import org.springframework.data.domain.Page;

public record InventoryPageResponse(
    List<InventoryResponse> inventories,
    int page,
    int size,
    long totalElements,
    int totalPages
) {
    public InventoryPageResponse {
        inventories = List.copyOf(inventories);
    }

    public static InventoryPageResponse from(Page<InventoryResponse> page) {
        return new InventoryPageResponse(
            page.getContent(),
            page.getNumber(),
            page.getSize(),
            page.getTotalElements(),
            page.getTotalPages()
        );
    }
}
