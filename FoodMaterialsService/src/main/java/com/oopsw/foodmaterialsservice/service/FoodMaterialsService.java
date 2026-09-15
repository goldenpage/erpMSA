package com.oopsw.foodmaterialsservice.service;

import com.oopsw.foodmaterialsservice.api.ApiErrorCode;
import com.oopsw.foodmaterialsservice.api.ApiException;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialEntity;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialRepository;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialStatus;
import com.oopsw.foodmaterialsservice.web.dto.CreateFoodMaterialRequest;
import com.oopsw.foodmaterialsservice.web.dto.FoodMaterialPageResponse;
import com.oopsw.foodmaterialsservice.web.dto.FoodMaterialResponse;
import com.oopsw.foodmaterialsservice.web.dto.UpdateFoodMaterialRequest;
import java.util.Locale;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class FoodMaterialsService {

    private final FoodMaterialRepository itemRepository;

    @Transactional
    public FoodMaterialResponse create(Long accountId, CreateFoodMaterialRequest request) {
        String sku = normalizeSku(request.sku());

        if (itemRepository.existsByAccountIdAndSku(accountId, sku)) {
            throw new ApiException(ApiErrorCode.SKU_ALREADY_EXISTS);
        }

        FoodMaterialEntity item = FoodMaterialEntity.create(
            accountId,
            sku,
            request.name().trim(),
            normalizeDescription(request.description()),
            request.unitPrice()
        );

        return FoodMaterialResponse.from(itemRepository.saveAndFlush(item));
    }

    @Transactional(readOnly = true)
    public FoodMaterialResponse get(Long accountId, Long foodMaterialId) {
        return FoodMaterialResponse.from(findOwnedFoodMaterial(accountId, foodMaterialId));
    }

    @Transactional(readOnly = true)
    public FoodMaterialPageResponse list(
        Long accountId,
        FoodMaterialStatus status,
        int page,
        int size
    ) {
        PageRequest pageable = PageRequest.of(
            page,
            size,
            Sort.by(Sort.Direction.DESC, "createdAt", "id")
        );

        Page<FoodMaterialEntity> foodMaterials = status == null
            ? itemRepository.findAllByAccountId(accountId, pageable)
            : itemRepository.findAllByAccountIdAndStatus(
                accountId,
                status,
                pageable
            );

        return FoodMaterialPageResponse.fromFoodMaterials(foodMaterials.map(FoodMaterialResponse::from));
    }

    @Transactional
    public FoodMaterialResponse update(
        Long accountId,
        Long foodMaterialId,
        UpdateFoodMaterialRequest request
    ) {
        FoodMaterialEntity item = findOwnedFoodMaterial(accountId, foodMaterialId);

        if (!Objects.equals(item.getVersion(), request.version())) {
            throw new ApiException(ApiErrorCode.FOOD_MATERIAL_CONFLICT);
        }

        item.update(
            request.name().trim(),
            normalizeDescription(request.description()),
            request.unitPrice(),
            request.status()
        );
        return FoodMaterialResponse.from(itemRepository.saveAndFlush(item));
    }

    @Transactional
    public void deactivate(Long accountId, Long foodMaterialId) {
        FoodMaterialEntity item = findOwnedFoodMaterial(accountId, foodMaterialId);
        item.deactivate();
        itemRepository.saveAndFlush(item);
    }

    private FoodMaterialEntity findOwnedFoodMaterial(Long accountId, Long foodMaterialId) {
        return itemRepository.findByIdAndAccountId(foodMaterialId, accountId)
            .orElseThrow(() -> new ApiException(
                ApiErrorCode.FOOD_MATERIAL_NOT_FOUND
            ));
    }

    private String normalizeSku(String sku) {
        return sku.trim().toUpperCase(Locale.ROOT);
    }

    private String normalizeDescription(String description) {
        if (description == null || description.isBlank()) {
            return null;
        }
        return description.trim();
    }
}
