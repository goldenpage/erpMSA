package com.oopsw.auditservice.event;

import java.time.Instant;
import java.util.UUID;

@com.fasterxml.jackson.annotation.JsonIgnoreProperties(ignoreUnknown = true)
public record AccountRegisteredEvent(
    UUID eventId,
    int eventVersion,
    Long accountId,
    String role,
    String status,
    Instant occurredAt
) {
}
