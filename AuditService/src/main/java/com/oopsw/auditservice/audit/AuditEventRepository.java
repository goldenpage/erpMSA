package com.oopsw.auditservice.audit;

import java.time.Instant;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AuditEventRepository
    extends JpaRepository<AuditEventEntity, Long> {

    boolean existsByEventId(String eventId);

    @Modifying
    @Query(value = """
        INSERT INTO audit_event (
            event_id,
            event_type,
            event_version,
            aggregate_id,
            role,
            account_status,
            occurred_at,
            received_at,
            payload
        ) VALUES (
            :eventId,
            :eventType,
            :eventVersion,
            :aggregateId,
            :role,
            :accountStatus,
            :occurredAt,
            :receivedAt,
            :payload
        )
        ON DUPLICATE KEY UPDATE event_id = VALUES(event_id)
        """, nativeQuery = true)
    int insertIfAbsent(
        @Param("eventId") String eventId,
        @Param("eventType") String eventType,
        @Param("eventVersion") int eventVersion,
        @Param("aggregateId") String aggregateId,
        @Param("role") String role,
        @Param("accountStatus") String accountStatus,
        @Param("occurredAt") Instant occurredAt,
        @Param("receivedAt") Instant receivedAt,
        @Param("payload") String payload
    );
}
