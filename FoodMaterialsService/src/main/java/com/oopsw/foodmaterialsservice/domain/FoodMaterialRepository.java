package com.oopsw.foodmaterialsservice.domain;

import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FoodMaterialRepository extends JpaRepository<FoodMaterialEntity, Long> {

    boolean existsByAccountIdAndSku(Long accountId, String sku);

    Optional<FoodMaterialEntity> findByIdAndAccountId(Long id, Long accountId);

    Page<FoodMaterialEntity> findAllByAccountId(Long accountId, Pageable pageable);

    Page<FoodMaterialEntity> findAllByAccountIdAndStatus(
        Long accountId,
        FoodMaterialStatus status,
        Pageable pageable
    );
}
