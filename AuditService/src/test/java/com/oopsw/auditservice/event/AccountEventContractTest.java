package com.oopsw.auditservice.event;

import com.oopsw.auditservice.audit.AuditEventRepository;
import tools.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AccountEventContractTest {
    private final AuditEventRepository repository = mock(AuditEventRepository.class);
    private final AccountEventConsumer consumer = new AccountEventConsumer(repository, new ObjectMapper());
    private static final String VALID = """
        {"eventId":"b9687d7a-0955-49a4-bd53-0030de1876a8","eventVersion":1,
         "accountId":1,"role":"ROLE_USER","status":"ACTIVE","occurredAt":"2026-09-01T00:00:00Z"}
        """;

    @Test
    void 선택필드_추가는_구버전_소비자를_깨뜨리지_않는다() {
        consumer.consume(VALID.replace("\"eventVersion\":1", "\"eventVersion\":1,\"traceId\":\"future\""));
        verify(repository).insertIfAbsent(anyString(), eq("AccountRegistered"), eq(1), eq("1"),
            eq("ROLE_USER"), eq("ACTIVE"), any(), any(), anyString());
    }

    @Test
    void 잘못된_JSON_버전_필수값은_DB저장_전에_거절한다() {
        for (String payload : new String[]{"{", "null", VALID.replace("\"eventVersion\":1", "\"eventVersion\":2"),
            VALID.replace("\"accountId\":1", "\"accountId\":-1"), VALID.replace("\"role\":\"ROLE_USER\"", "\"role\":\"\"")}) {
            assertThatThrownBy(() -> consumer.consume(payload)).isInstanceOf(IllegalArgumentException.class);
        }
        verifyNoInteractions(repository);
    }
}
