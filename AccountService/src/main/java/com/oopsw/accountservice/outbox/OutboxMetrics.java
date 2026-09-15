package com.oopsw.accountservice.outbox;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Instant;
import org.springframework.dao.DataAccessException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** DB access is sampled, never performed by the Prometheus scrape thread. */
@Component
public class OutboxMetrics {
    private final AccountOutboxRepository repository;
    private volatile Snapshot snapshot = new Snapshot(Double.NaN, null, false);

    public OutboxMetrics(AccountOutboxRepository repository, MeterRegistry registry) {
        this.repository = repository;
        Gauge.builder("account.outbox.pending", this, m -> m.snapshot.pending()).register(registry);
        Gauge.builder("account.outbox.oldest.age", this, m -> m.oldestAge())
            .baseUnit("seconds").register(registry);
        Gauge.builder("account.outbox.sample.healthy", this, m -> m.snapshot.healthy() ? 1 : 0).register(registry);
    }

    @Scheduled(fixedDelayString = "${app.kafka.outbox.metrics-delay:5s}")
    @Transactional(readOnly = true)
    public void sample() {
        try {
            long count = repository.countByStatus(OutboxStatus.PENDING);
            Instant oldest = repository.oldestCreatedAt(OutboxStatus.PENDING);
            snapshot = new Snapshot(count, oldest, true);
        } catch (DataAccessException exception) {
            snapshot = new Snapshot(Double.NaN, null, false);
        }
    }

    private double oldestAge() {
        Snapshot current = snapshot;
        if (!current.healthy()) return Double.NaN;
        return current.oldest() == null ? 0 : Math.max(0, Instant.now().getEpochSecond() - current.oldest().getEpochSecond());
    }
    private record Snapshot(double pending, Instant oldest, boolean healthy) {}
}
