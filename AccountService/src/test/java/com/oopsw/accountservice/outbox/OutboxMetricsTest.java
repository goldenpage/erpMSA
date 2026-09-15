package com.oopsw.accountservice.outbox;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class OutboxMetricsTest {
    @Test
    void 적체와_지연을_측정하고_DB장애를_정상값으로_숨기지_않는다() {
        var repository = mock(AccountOutboxRepository.class);
        var registry = new SimpleMeterRegistry();
        try {
            var metrics = new OutboxMetrics(repository, registry);
            when(repository.countByStatus(OutboxStatus.PENDING)).thenReturn(3L);
            when(repository.oldestCreatedAt(OutboxStatus.PENDING)).thenReturn(Instant.now().minusSeconds(20));
            metrics.sample();
            assertThat(registry.get("account.outbox.pending").gauge().value()).isEqualTo(3);
            assertThat(registry.get("account.outbox.oldest.age").gauge().value()).isBetween(20.0, 22.0);
            when(repository.countByStatus(OutboxStatus.PENDING)).thenThrow(new DataAccessResourceFailureException("offline"));
            metrics.sample();
            assertThat(registry.get("account.outbox.pending").gauge().value()).isNaN();
            assertThat(registry.get("account.outbox.sample.healthy").gauge().value()).isZero();
        } finally { registry.close(); }
    }
}
