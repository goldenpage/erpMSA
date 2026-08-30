package com.oopsw.accountservice.outbox;

import java.time.Instant;
import java.util.UUID;

public record AccountRegisteredEvent(
    UUID eventId,
    int eventVersion,
    Long accountId,
    String role,
    String status,
    Instant occurredAt
) {
}
