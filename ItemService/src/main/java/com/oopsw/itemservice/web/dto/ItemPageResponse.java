package com.oopsw.itemservice.web.dto;

import java.util.List;
import org.springframework.data.domain.Page;

public record ItemPageResponse(
    List<ItemResponse> items,
    int page,
    int size,
    long totalElements,
    int totalPages
) {
    public ItemPageResponse {
        items = List.copyOf(items);
    }

    public static ItemPageResponse fromItems(Page<ItemResponse> page) {
        return new ItemPageResponse(
            page.getContent(),
            page.getNumber(),
            page.getSize(),
            page.getTotalElements(),
            page.getTotalPages()
        );
    }
}
