package com.oopsw.inventoryservice.domain;

import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InventoryRepository extends JpaRepository<InventoryEntity, Long> {

    boolean existsByAccountIdAndItemId(Long accountId, Long itemId);

    Optional<InventoryEntity> findByAccountIdAndItemId(
        Long accountId,
        Long itemId
    );

    Page<InventoryEntity> findAllByAccountId(
        Long accountId,
        Pageable pageable
    );
}
