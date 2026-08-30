package com.oopsw.accountservice.outbox;

import java.time.Instant;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AccountOutboxRepository
    extends JpaRepository<AccountOutboxEvent, Long> {

    List<AccountOutboxEvent>
        findTop100ByStatusAndNextAttemptAtLessThanEqualOrderByCreatedAtAsc(
            OutboxStatus status,
            Instant nextAttemptAt
        );
}
