package com.oopsw.foodmaterialsservice.inventory.domain;

import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InventoryRepository extends JpaRepository<InventoryEntity, Long> {

    boolean existsByAccountIdAndFoodMaterialId(Long accountId, Long foodMaterialId);

    Optional<InventoryEntity> findByAccountIdAndFoodMaterialId(
        Long accountId,
        Long foodMaterialId
    );

    Page<InventoryEntity> findAllByAccountId(
        Long accountId,
        Pageable pageable
    );
}
