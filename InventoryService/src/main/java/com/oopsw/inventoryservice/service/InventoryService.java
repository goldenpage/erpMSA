package com.oopsw.inventoryservice.service;

import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import com.oopsw.inventoryservice.domain.InventoryEntity;
import com.oopsw.inventoryservice.domain.InventoryRepository;
import com.oopsw.inventoryservice.domain.StockMovementEntity;
import com.oopsw.inventoryservice.domain.StockMovementRepository;
import com.oopsw.inventoryservice.web.dto.AdjustInventoryRequest;
import com.oopsw.inventoryservice.web.dto.InventoryAdjustmentResponse;
import com.oopsw.inventoryservice.web.dto.InventoryPageResponse;
import com.oopsw.inventoryservice.web.dto.InventoryResponse;
import com.oopsw.inventoryservice.web.dto.StockMovementPageResponse;
import com.oopsw.inventoryservice.web.dto.StockMovementResponse;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class InventoryService {

    private final InventoryRepository inventoryRepository;
    private final StockMovementRepository movementRepository;

    @Transactional
    public InventoryResponse create(
        Long accountId,
        Long itemId,
        Long initialQuantity
    ) {
        if (inventoryRepository.existsByAccountIdAndItemId(
            accountId,
            itemId
        )) {
            throw new ApiException(ApiErrorCode.INVENTORY_ALREADY_EXISTS);
        }

        InventoryEntity inventory = InventoryEntity.create(
            accountId,
            itemId,
            initialQuantity
        );

        try {
            InventoryEntity saved = inventoryRepository.saveAndFlush(inventory);
            movementRepository.saveAndFlush(
                StockMovementEntity.initial(saved)
            );
            return InventoryResponse.from(saved);
        } catch (DataIntegrityViolationException exception) {
            throw new ApiException(ApiErrorCode.INVENTORY_ALREADY_EXISTS);
        }
    }

    @Transactional(readOnly = true)
    public InventoryResponse get(Long accountId, Long itemId) {
        return InventoryResponse.from(findInventory(accountId, itemId));
    }

    @Transactional(readOnly = true)
    public InventoryPageResponse list(
        Long accountId,
        int page,
        int size
    ) {
        PageRequest pageable = PageRequest.of(
            page,
            size,
            Sort.by(Sort.Direction.DESC, "updatedAt")
        );
        Page<InventoryResponse> inventories = inventoryRepository
            .findAllByAccountId(accountId, pageable)
            .map(InventoryResponse::from);
        return InventoryPageResponse.from(inventories);
    }

    @Transactional
    public InventoryAdjustmentResponse adjust(
        Long accountId,
        Long itemId,
        AdjustInventoryRequest request
    ) {
        if (request.quantityDelta() == 0L) {
            throw new ApiException(ApiErrorCode.INVALID_REQUEST);
        }

        String requestId = request.requestId().trim();

        if (movementRepository.existsByAccountIdAndRequestId(
            accountId,
            requestId
        )) {
            throw new ApiException(
                ApiErrorCode.ADJUSTMENT_ALREADY_EXISTS
            );
        }

        InventoryEntity inventory = findInventory(accountId, itemId);

        if (!Objects.equals(inventory.getVersion(), request.version())) {
            throw new ApiException(ApiErrorCode.INVENTORY_CONFLICT);
        }

        long quantityAfter;

        try {
            quantityAfter = Math.addExact(
                inventory.getOnHandQuantity(),
                request.quantityDelta()
            );
        } catch (ArithmeticException exception) {
            throw new ApiException(ApiErrorCode.INVALID_REQUEST);
        }

        if (quantityAfter < 0) {
            throw new ApiException(ApiErrorCode.INSUFFICIENT_STOCK);
        }

        InventoryEntity.QuantityChange change = inventory.adjust(
            request.quantityDelta()
        );
        StockMovementEntity movement = StockMovementEntity.adjustment(
            inventory,
            requestId,
            request.quantityDelta(),
            change,
            request.reason().trim()
        );

        try {
            InventoryEntity savedInventory =
                inventoryRepository.saveAndFlush(inventory);
            StockMovementEntity savedMovement =
                movementRepository.saveAndFlush(movement);
            return new InventoryAdjustmentResponse(
                InventoryResponse.from(savedInventory),
                StockMovementResponse.from(savedMovement)
            );
        } catch (DataIntegrityViolationException exception) {
            throw new ApiException(
                ApiErrorCode.ADJUSTMENT_ALREADY_EXISTS
            );
        }
    }

    @Transactional(readOnly = true)
    public StockMovementPageResponse movements(
        Long accountId,
        Long itemId,
        int page,
        int size
    ) {
        InventoryEntity inventory = findInventory(accountId, itemId);
        PageRequest pageable = PageRequest.of(
            page,
            size,
            Sort.by(Sort.Direction.DESC, "createdAt")
        );
        Page<StockMovementResponse> movements = movementRepository
            .findAllByInventoryId(inventory.getId(), pageable)
            .map(StockMovementResponse::from);
        return StockMovementPageResponse.from(movements);
    }

    private InventoryEntity findInventory(Long accountId, Long itemId) {
        return inventoryRepository.findByAccountIdAndItemId(
            accountId,
            itemId
        ).orElseThrow(() -> new ApiException(
            ApiErrorCode.INVENTORY_NOT_FOUND
        ));
    }
}
