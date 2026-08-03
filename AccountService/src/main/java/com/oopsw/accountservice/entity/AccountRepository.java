package com.oopsw.accountservice.entity;

import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AccountRepository extends JpaRepository<AccountEntity, Long> {

    Optional<AccountEntity> findByEmail(String email);

    boolean existsByEmail(String email);

    boolean existsByBusinessId(String businessId);
}
