package com.oopsw.accountservice.outbox;

import com.oopsw.accountservice.entity.AccountEntity;
import java.time.Instant;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
@RequiredArgsConstructor
public class AccountEventOutbox {

    private final AccountOutboxRepository outboxRepository;
    private final ObjectMapper objectMapper;

    @Value("${app.kafka.topics.account-lifecycle}")
    private String accountLifecycleTopic;

    public void enqueueRegistered(AccountEntity account) {
        UUID eventId = UUID.randomUUID();
        Instant occurredAt = account.getCreatedAt() == null
            ? Instant.now()
            : account.getCreatedAt();
        AccountRegisteredEvent event = new AccountRegisteredEvent(
            eventId,
            1,
            account.getId(),
            account.getRole().name(),
            account.getReviewStatus().name(),
            occurredAt
        );

        try {
            outboxRepository.save(AccountOutboxEvent.pending(
                eventId,
                accountLifecycleTopic,
                account.getId().toString(),
                objectMapper.writeValueAsString(event),
                occurredAt
            ));
        } catch (JacksonException exception) {
            throw new IllegalStateException(
                "회원가입 이벤트 직렬화에 실패했습니다.",
                exception
            );
        }
    }
}
