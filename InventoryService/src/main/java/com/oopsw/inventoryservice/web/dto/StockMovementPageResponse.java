package com.oopsw.inventoryservice.web.dto;

import java.util.List;
import org.springframework.data.domain.Page;

public record StockMovementPageResponse(
    List<StockMovementResponse> movements,
    int page,
    int size,
    long totalElements,
    int totalPages
) {
    public StockMovementPageResponse {
        movements = List.copyOf(movements);
    }

    public static StockMovementPageResponse from(
        Page<StockMovementResponse> page
    ) {
        return new StockMovementPageResponse(
            page.getContent(),
            page.getNumber(),
            page.getSize(),
            page.getTotalElements(),
            page.getTotalPages()
        );
    }
}
