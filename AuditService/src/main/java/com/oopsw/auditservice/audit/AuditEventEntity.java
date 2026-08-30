package com.oopsw.auditservice.audit;

import com.oopsw.auditservice.event.AccountRegisteredEvent;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "audit_event")
@NoArgsConstructor
public class AuditEventEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "event_id", nullable = false, unique = true, length = 36)
    private String eventId;

    @Column(name = "event_type", nullable = false, length = 100)
    private String eventType;

    @Column(name = "event_version", nullable = false)
    private int eventVersion;

    @Column(name = "aggregate_id", nullable = false, length = 100)
    private String aggregateId;

    @Column(nullable = false, length = 30)
    private String role;

    @Column(name = "account_status", nullable = false, length = 30)
    private String accountStatus;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(name = "received_at", nullable = false)
    private Instant receivedAt;

    @Column(nullable = false, columnDefinition = "LONGTEXT")
    private String payload;

    public static AuditEventEntity accountRegistered(
        AccountRegisteredEvent event,
        String payload,
        Instant receivedAt
    ) {
        AuditEventEntity auditEvent = new AuditEventEntity();
        auditEvent.eventId = event.eventId().toString();
        auditEvent.eventType = "AccountRegistered";
        auditEvent.eventVersion = event.eventVersion();
        auditEvent.aggregateId = event.accountId().toString();
        auditEvent.role = event.role();
        auditEvent.accountStatus = event.status();
        auditEvent.occurredAt = event.occurredAt();
        auditEvent.receivedAt = receivedAt;
        auditEvent.payload = payload;
        return auditEvent;
    }
}
