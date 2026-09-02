package com.oopsw.inventoryservice.domain;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StockMovementRepository
    extends JpaRepository<StockMovementEntity, Long> {

    boolean existsByAccountIdAndRequestId(Long accountId, String requestId);

    Page<StockMovementEntity> findAllByInventoryId(
        Long inventoryId,
        Pageable pageable
    );
}
