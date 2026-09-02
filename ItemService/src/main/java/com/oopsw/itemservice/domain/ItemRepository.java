package com.oopsw.itemservice.domain;

import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ItemRepository extends JpaRepository<ItemEntity, Long> {

    boolean existsByAccountIdAndSku(Long accountId, String sku);

    Optional<ItemEntity> findByIdAndAccountId(Long id, Long accountId);

    Page<ItemEntity> findAllByAccountId(Long accountId, Pageable pageable);

    Page<ItemEntity> findAllByAccountIdAndStatus(
        Long accountId,
        ItemStatus status,
        Pageable pageable
    );
}
