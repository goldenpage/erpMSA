package com.oopsw.accountservice.outbox;

import java.time.Instant;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class OutboxPublisher {

    private final AccountOutboxRepository outboxRepository;
    private final OutboxPublicationService publicationService;

    @Scheduled(fixedDelayString = "${app.kafka.outbox.publish-delay}")
    public void publishPendingEvents() {
        outboxRepository
            .findTop100ByStatusAndNextAttemptAtLessThanEqualOrderByCreatedAtAsc(
                OutboxStatus.PENDING,
                Instant.now()
            )
            .stream()
            .map(AccountOutboxEvent::getId)
            .forEach(publicationService::publish);
    }
}
