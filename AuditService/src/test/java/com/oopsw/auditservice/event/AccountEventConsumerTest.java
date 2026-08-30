package com.oopsw.auditservice.event;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.oopsw.auditservice.audit.AuditEventRepository;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.ObjectMapper;

@ExtendWith(MockitoExtension.class)
class AccountEventConsumerTest {

    private static final String PAYLOAD = "{\"event\":\"test\"}";

    @Mock
    private AuditEventRepository auditEventRepository;

    @Mock
    private ObjectMapper objectMapper;

    @InjectMocks
    private AccountEventConsumer accountEventConsumer;

    private AccountRegisteredEvent event;

    @BeforeEach
    void setUp() throws Exception {
        event = new AccountRegisteredEvent(
            UUID.randomUUID(),
            1,
            1L,
            "ROLE_USER",
            "ACTIVE",
            Instant.parse("2026-08-30T00:00:00Z")
        );
        when(objectMapper.readValue(PAYLOAD, AccountRegisteredEvent.class))
            .thenReturn(event);
    }

    @Test
    void 회원가입_이벤트를_감사_로그로_저장한다() {
        when(auditEventRepository.existsByEventId(event.eventId().toString()))
            .thenReturn(false);

        accountEventConsumer.consume(PAYLOAD);

        verify(auditEventRepository).insertIfAbsent(
            eq(event.eventId().toString()),
            eq("AccountRegistered"),
            eq(1),
            eq("1"),
            eq("ROLE_USER"),
            eq("ACTIVE"),
            eq(event.occurredAt()),
            any(Instant.class),
            eq(PAYLOAD)
        );
    }

    @Test
    void 이미_처리한_이벤트는_중복_저장하지_않는다() {
        when(auditEventRepository.existsByEventId(event.eventId().toString()))
            .thenReturn(true);

        accountEventConsumer.consume(PAYLOAD);

        verify(auditEventRepository, never()).insertIfAbsent(
            any(),
            any(),
            any(Integer.class),
            any(),
            any(),
            any(),
            any(Instant.class),
            any(Instant.class),
            any()
        );
    }
}
