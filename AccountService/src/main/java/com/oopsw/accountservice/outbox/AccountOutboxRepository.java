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

    /**
     * 발행 대상 이벤트를 잠근다. 다른 인스턴스가 잠근 행은 기다리지 않고 건너뛴다(MariaDB 10.6+).
     * 트랜잭션 안에서 호출해야 하며, 잠금은 커밋 때 풀린다.
     *
     * <p>정렬은 인덱스 idx_account_outbox_pending(status, next_attempt_at, created_at) 순서를 따른다.
     * 인덱스와 다른 순서로 정렬하면 정렬 전에 조건에 맞는 모든 행을 읽고 잠가 LIMIT 밖의 행까지 다른 인스턴스가 못 가져간다.
     */
    @Query(value = """
        SELECT * FROM account_outbox_event
        WHERE status = 'PENDING' AND next_attempt_at <= :now
        ORDER BY next_attempt_at, created_at
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
        """, nativeQuery = true)
    List<AccountOutboxEvent> lockPublishable(
        @org.springframework.data.repository.query.Param("now") Instant now,
        @org.springframework.data.repository.query.Param("limit") int limit
    );
}
