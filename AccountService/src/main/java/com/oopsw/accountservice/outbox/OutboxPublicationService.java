package com.oopsw.accountservice.outbox;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.TimeUnit;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class OutboxPublicationService {

    private final AccountOutboxRepository outboxRepository;
    private final KafkaTemplate<String, String> kafkaTemplate;

    @Value("${app.kafka.outbox.retry-delay}")
    private Duration retryDelay;

    @Transactional
    public void publish(Long outboxId) {
        AccountOutboxEvent event = outboxRepository.findById(outboxId)
            .orElse(null);

        if (event == null || event.getStatus() != OutboxStatus.PENDING) {
            return;
        }

        try {
            kafkaTemplate.send(
                event.getTopic(),
                event.getEventKey(),
                event.getPayload()
            ).get(10, TimeUnit.SECONDS);
            event.markPublished(Instant.now());
        } catch (Exception exception) {
            event.markFailed(
                Instant.now(),
                retryDelay,
                exception.getMessage()
            );

            if (exception instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
