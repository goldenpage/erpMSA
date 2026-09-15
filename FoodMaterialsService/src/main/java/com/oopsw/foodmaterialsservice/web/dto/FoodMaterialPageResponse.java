package com.oopsw.foodmaterialsservice.web.dto;

import java.util.List;
import org.springframework.data.domain.Page;

public record FoodMaterialPageResponse(
    List<FoodMaterialResponse> foodMaterials,
    int page,
    int size,
    long totalElements,
    int totalPages
) {
    public FoodMaterialPageResponse {
        foodMaterials = List.copyOf(foodMaterials);
    }

    public static FoodMaterialPageResponse fromFoodMaterials(Page<FoodMaterialResponse> page) {
        return new FoodMaterialPageResponse(
            page.getContent(),
            page.getNumber(),
            page.getSize(),
            page.getTotalElements(),
            page.getTotalPages()
        );
    }
}
