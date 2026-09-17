package com.oopsw.foodmaterialsservice.inventory.domain;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StockMovementRepository
    extends JpaRepository<StockMovementEntity, Long> {

    java.util.Optional<StockMovementEntity> findByAccountIdAndRequestId(Long accountId, String requestId);

    boolean existsByAccountIdAndRequestId(Long accountId, String requestId);

    Page<StockMovementEntity> findAllByInventoryId(
        Long inventoryId,
        Pageable pageable
    );
}
