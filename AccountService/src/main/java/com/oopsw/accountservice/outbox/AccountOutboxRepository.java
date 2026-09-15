package com.oopsw.accountservice.outbox;

import java.time.Instant;
import java.util.List;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AccountOutboxRepository
    extends JpaRepository<AccountOutboxEvent, Long> {

    long countByStatus(OutboxStatus status);

    @Query("select min(e.createdAt) from AccountOutboxEvent e where e.status = :status")
    Instant oldestCreatedAt(@org.springframework.data.repository.query.Param("status") OutboxStatus status);

    List<AccountOutboxEvent>
        findTop100ByStatusAndNextAttemptAtLessThanEqualOrderByCreatedAtAsc(
            OutboxStatus status,
            Instant nextAttemptAt
        );
}
