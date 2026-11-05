package com.oopsw.accountservice.outbox;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxPublisher {

    private final OutboxClaimService claimService;
    private final OutboxPublicationService publicationService;
    private final Clock clock;
    private final Duration claimLease;
    private final Duration leaseSafetyMargin;
    private final int batchSize;

    @Autowired
    public OutboxPublisher(
        OutboxClaimService claimService,
        OutboxPublicationService publicationService,
        @Value("${app.kafka.outbox.claim-lease:120s}") Duration claimLease,
        @Value("${app.kafka.outbox.lease-safety-margin:30s}") Duration leaseSafetyMargin,
        @Value("${app.kafka.outbox.batch-size:100}") int batchSize
    ) {
        this(claimService, publicationService, Clock.systemUTC(), claimLease, leaseSafetyMargin, batchSize);
    }

    OutboxPublisher(
        OutboxClaimService claimService,
        OutboxPublicationService publicationService,
        Clock clock,
        Duration claimLease,
        Duration leaseSafetyMargin,
        int batchSize
    ) {
        if (!claimLease.minus(leaseSafetyMargin).isPositive() || batchSize < 1) {
            throw new IllegalArgumentException("claim-lease must exceed lease-safety-margin and batch-size must be positive");
        }
        this.claimService = claimService;
        this.publicationService = publicationService;
        this.clock = clock;
        this.claimLease = claimLease;
        this.leaseSafetyMargin = leaseSafetyMargin;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${app.kafka.outbox.publish-delay}")
    public void publishPendingEvents() {
        Instant now = clock.instant();
        Instant leaseUntil = now.plus(claimLease);
        List<Long> claimed = claimService.claim(now, leaseUntil, batchSize);
        // 선점이 끝나기 전에 멈춘다. 만료 뒤에도 계속 발행하면 다른 인스턴스가 같은 이벤트를 다시 선점해 중복 발행할 수 있다.
        // 남은 이벤트는 선점 만료 뒤 다시 발행 대상이 된다.
        Instant stopAt = leaseUntil.minus(leaseSafetyMargin);
        for (Long id : claimed) {
            if (!clock.instant().isBefore(stopAt)) {
                break;
            }
            publicationService.publish(id);
        }
    }
}
