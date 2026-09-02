package com.oopsw.itemservice.service;

import com.oopsw.itemservice.api.ApiErrorCode;
import com.oopsw.itemservice.api.ApiException;
import com.oopsw.itemservice.domain.ItemEntity;
import com.oopsw.itemservice.domain.ItemRepository;
import com.oopsw.itemservice.domain.ItemStatus;
import com.oopsw.itemservice.web.dto.CreateItemRequest;
import com.oopsw.itemservice.web.dto.ItemPageResponse;
import com.oopsw.itemservice.web.dto.ItemResponse;
import com.oopsw.itemservice.web.dto.UpdateItemRequest;
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
public class ItemService {

    private final ItemRepository itemRepository;

    @Transactional
    public ItemResponse create(Long accountId, CreateItemRequest request) {
        String sku = normalizeSku(request.sku());

        if (itemRepository.existsByAccountIdAndSku(accountId, sku)) {
            throw new ApiException(ApiErrorCode.SKU_ALREADY_EXISTS);
        }

        ItemEntity item = ItemEntity.create(
            accountId,
            sku,
            request.name().trim(),
            normalizeDescription(request.description()),
            request.unitPrice()
        );

        return ItemResponse.from(itemRepository.saveAndFlush(item));
    }

    @Transactional(readOnly = true)
    public ItemResponse get(Long accountId, Long itemId) {
        return ItemResponse.from(findOwnedItem(accountId, itemId));
    }

    @Transactional(readOnly = true)
    public ItemPageResponse list(
        Long accountId,
        ItemStatus status,
        int page,
        int size
    ) {
        PageRequest pageable = PageRequest.of(
            page,
            size,
            Sort.by(Sort.Direction.DESC, "createdAt")
        );

        Page<ItemEntity> items = status == null
            ? itemRepository.findAllByAccountId(accountId, pageable)
            : itemRepository.findAllByAccountIdAndStatus(
                accountId,
                status,
                pageable
            );

        return ItemPageResponse.fromItems(items.map(ItemResponse::from));
    }

    @Transactional
    public ItemResponse update(
        Long accountId,
        Long itemId,
        UpdateItemRequest request
    ) {
        ItemEntity item = findOwnedItem(accountId, itemId);

        if (!Objects.equals(item.getVersion(), request.version())) {
            throw new ApiException(ApiErrorCode.ITEM_CONFLICT);
        }

        item.update(
            request.name().trim(),
            normalizeDescription(request.description()),
            request.unitPrice(),
            request.status()
        );
        return ItemResponse.from(itemRepository.saveAndFlush(item));
    }

    @Transactional
    public void deactivate(Long accountId, Long itemId) {
        ItemEntity item = findOwnedItem(accountId, itemId);
        item.deactivate();
        itemRepository.saveAndFlush(item);
    }

    private ItemEntity findOwnedItem(Long accountId, Long itemId) {
        return itemRepository.findByIdAndAccountId(itemId, accountId)
            .orElseThrow(() -> new ApiException(
                ApiErrorCode.ITEM_NOT_FOUND
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
