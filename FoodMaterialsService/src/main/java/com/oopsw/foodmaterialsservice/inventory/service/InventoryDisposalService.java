package com.oopsw.foodmaterialsservice.inventory.service;

import com.oopsw.foodmaterialsservice.api.*;
import com.oopsw.foodmaterialsservice.inventory.domain.*;
import com.oopsw.foodmaterialsservice.inventory.web.dto.*;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class InventoryDisposalService {
    private final InventoryRepository inventoryRepository;
    private final StockMovementRepository movementRepository;

    @Transactional("inventoryTransactionManager")
    public StockMovementResponse dispose(long accountId,long foodMaterialId,DisposeInventoryRequest request) {
        var inventory=inventoryRepository.lockOwned(accountId,foodMaterialId)
            .orElseThrow(()->new ApiException(ApiErrorCode.INVENTORY_NOT_FOUND));
        var existing=movementRepository.findByAccountIdAndRequestId(accountId,request.requestId());
        if(existing.isPresent()) {
            var movement=existing.get();
            if(!Objects.equals(movement.getFoodMaterialId(),foodMaterialId)
                || movement.getMovementType()!=MovementType.DISPOSAL
                || movement.getQuantityDelta()!=-request.quantity()
                || !movement.getReason().equals(request.reason().trim())) {
                throw new ApiException(ApiErrorCode.DISPOSAL_REQUEST_CONFLICT);
            }
            return StockMovementResponse.from(movement);
        }
        if(request.quantity()>inventory.getOnHandQuantity()) throw new ApiException(ApiErrorCode.INSUFFICIENT_STOCK);
        var change=inventory.adjust(-request.quantity());
        var movement=StockMovementEntity.disposal(inventory,request.requestId(),request.quantity(),change,request.reason().trim());
        try {
            inventoryRepository.saveAndFlush(inventory);
            return StockMovementResponse.from(movementRepository.saveAndFlush(movement));
        } catch(DataIntegrityViolationException exception) {
            throw new ApiException(ApiErrorCode.DISPOSAL_REQUEST_CONFLICT);
        }
    }
}
