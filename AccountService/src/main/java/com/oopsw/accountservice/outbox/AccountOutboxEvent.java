package com.oopsw.accountservice.outbox;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "account_outbox_event")
@NoArgsConstructor
public class AccountOutboxEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "event_id", nullable = false, unique = true, length = 36)
    private String eventId;

    @Column(name = "aggregate_type", nullable = false, length = 50)
    private String aggregateType;

    @Column(name = "aggregate_id", nullable = false, length = 100)
    private String aggregateId;

    @Column(name = "event_type", nullable = false, length = 100)
    private String eventType;

    @Column(name = "event_version", nullable = false)
    private int eventVersion;

    @Column(nullable = false, length = 200)
    private String topic;

    @Column(name = "event_key", nullable = false, length = 100)
    private String eventKey;

    @Column(nullable = false, columnDefinition = "LONGTEXT")
    private String payload;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private OutboxStatus status;

    @Column(name = "attempt_count", nullable = false)
    private int attemptCount;

    @Column(name = "next_attempt_at", nullable = false)
    private Instant nextAttemptAt;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "published_at")
    private Instant publishedAt;

    @Column(name = "last_error", length = 1000)
    private String lastError;

    public static AccountOutboxEvent pending(
        UUID eventId,
        String topic,
        String eventKey,
        String payload,
        Instant createdAt
    ) {
        AccountOutboxEvent event = new AccountOutboxEvent();
        event.eventId = eventId.toString();
        event.aggregateType = "Account";
        event.aggregateId = eventKey;
        event.eventType = "AccountRegistered";
        event.eventVersion = 1;
        event.topic = topic;
        event.eventKey = eventKey;
        event.payload = payload;
        event.status = OutboxStatus.PENDING;
        event.attemptCount = 0;
        event.nextAttemptAt = createdAt;
        event.createdAt = createdAt;
        return event;
    }

    public void markPublished(Instant publishedAt) {
        this.status = OutboxStatus.PUBLISHED;
        this.publishedAt = publishedAt;
        this.lastError = null;
    }

    public void markFailed(
        Instant failedAt,
        Duration retryDelay,
        String errorMessage
    ) {
        this.attemptCount++;
        long multiplier = Math.min(attemptCount, 12);
        this.nextAttemptAt = failedAt.plus(retryDelay.multipliedBy(multiplier));
        this.lastError = abbreviate(errorMessage, 1000);
    }

    private String abbreviate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
