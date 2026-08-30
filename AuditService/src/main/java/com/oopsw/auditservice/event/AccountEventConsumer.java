package com.oopsw.auditservice.event;

import com.oopsw.auditservice.audit.AuditEventRepository;
import java.time.Instant;
import lombok.RequiredArgsConstructor;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
@RequiredArgsConstructor
public class AccountEventConsumer {

    private final AuditEventRepository auditEventRepository;
    private final ObjectMapper objectMapper;

    @Transactional
    @KafkaListener(topics = "${app.kafka.topics.account-lifecycle}")
    public void consume(String payload) {
        AccountRegisteredEvent event = readEvent(payload);
        validate(event);

        if (auditEventRepository.existsByEventId(event.eventId().toString())) {
            return;
        }

        auditEventRepository.insertIfAbsent(
            event.eventId().toString(),
            "AccountRegistered",
            event.eventVersion(),
            event.accountId().toString(),
            event.role(),
            event.status(),
            event.occurredAt(),
            Instant.now(),
            payload
        );
    }

    private AccountRegisteredEvent readEvent(String payload) {
        try {
            return objectMapper.readValue(
                payload,
                AccountRegisteredEvent.class
            );
        } catch (JacksonException exception) {
            throw new IllegalArgumentException(
                "AccountRegistered 이벤트를 역직렬화할 수 없습니다.",
                exception
            );
        }
    }

    private void validate(AccountRegisteredEvent event) {
        if (event == null ||
            event.eventId() == null ||
            event.eventVersion() != 1 ||
            event.accountId() == null ||
            event.occurredAt() == null) {
            throw new IllegalArgumentException(
                "지원하지 않거나 필수 값이 없는 AccountRegistered 이벤트입니다."
            );
        }
    }
}
