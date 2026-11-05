package com.oopsw.accountservice.outbox;

import java.time.Instant;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 여러 Account 인스턴스가 같은 Outbox 이벤트를 동시에 발행하지 않도록 발행 대상을 선점한다.
 *
 * <p>잠금을 건 짧은 트랜잭션 안에서 다음 시도 시각을 선점 만료 시각으로 미루고 커밋한다.
 * Kafka 발행은 이 트랜잭션 밖에서 하므로 브로커가 느려도 행 잠금을 오래 잡지 않는다.
 * 선점한 인스턴스가 중단되면 만료 뒤 다른 인스턴스가 다시 발행한다(at-least-once 유지).
 */
@Service
@RequiredArgsConstructor
public class OutboxClaimService {

    private final AccountOutboxRepository outboxRepository;

    @Transactional
    public List<Long> claim(Instant now, Instant leaseUntil, int limit) {
        List<AccountOutboxEvent> events = outboxRepository.lockPublishable(now, limit);
        events.forEach(event -> event.claimUntil(leaseUntil));
        return events.stream().map(AccountOutboxEvent::getId).toList();
    }
}
