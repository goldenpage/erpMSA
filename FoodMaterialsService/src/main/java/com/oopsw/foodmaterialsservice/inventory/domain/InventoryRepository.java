package com.oopsw.foodmaterialsservice.inventory.domain;

import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InventoryRepository extends JpaRepository<InventoryEntity, Long> {

    @org.springframework.data.jpa.repository.Lock(jakarta.persistence.LockModeType.PESSIMISTIC_WRITE)
    @org.springframework.data.jpa.repository.Query("select i from InventoryEntity i where i.accountId = :accountId and i.foodMaterialId = :foodMaterialId")
    Optional<InventoryEntity> lockOwned(long accountId, long foodMaterialId);

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
