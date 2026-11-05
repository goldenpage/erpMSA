package com.oopsw.accountservice.outbox;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.accountservice.support.TestcontainersConfiguration;
import com.oopsw.security.JwtTestKeys;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 실제 MariaDB에서 SKIP LOCKED 선점이 인스턴스 간 중복 발행을 막는지 검사한다.
 * 스케줄러가 테스트 이벤트를 발행하지 않도록 다음 시도 시각을 미래로 두고, claim에 그 이후 시각을 넘긴다.
 */
@SpringBootTest(properties = {
    "app.auth.secure-cookie=false",
    "app.kafka.outbox.publish-delay=100ms",
    "app.kafka.outbox.retry-delay=100ms",
    "eureka.client.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.jpa.hibernate.ddl-auto=validate"
})
@Import(TestcontainersConfiguration.class)
@org.junit.jupiter.api.Tag("integration")
class OutboxClaimIntegrationTest {

    @DynamicPropertySource
    static void jwtProperties(DynamicPropertyRegistry registry) {
        registry.add("app.auth.public-key-directory", JwtTestKeys.PRIMARY::publicDirectory);
        registry.add("app.auth.signing-key-id", JwtTestKeys.PRIMARY::kid);
        registry.add("app.auth.private-key-path", JwtTestKeys.PRIMARY::privatePath);
    }

    private static final Instant FUTURE = Instant.now().plus(1, ChronoUnit.DAYS).truncatedTo(ChronoUnit.SECONDS);

    @Autowired
    private AccountOutboxRepository outboxRepository;

    @Autowired
    private OutboxClaimService claimService;

    @Autowired
    private TransactionTemplate transactionTemplate;

    @AfterEach
    void cleanup() {
        outboxRepository.deleteAllInBatch();
    }

    @Test
    void 다른_트랜잭션이_잠근_이벤트는_기다리지_않고_건너뛰며_선점_만료_뒤에_다시_대상이_된다() throws Exception {
        List<AccountOutboxEvent> events = IntStream.range(0, 10).mapToObj(i -> {
            AccountOutboxEvent event = AccountOutboxEvent.pending(UUID.randomUUID(), "account.lifecycle.v1",
                String.valueOf(9_000_000 + i), "{}", FUTURE.minusSeconds(100 - i));
            event.claimUntil(FUTURE);
            return event;
        }).toList();
        outboxRepository.saveAllAndFlush(events);

        Instant now = FUTURE.plusSeconds(1);
        Instant leaseUntil = now.plusSeconds(120);
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch otherDone = new CountDownLatch(1);
        Set<Long> first = new HashSet<>();

        // 인스턴스 A: 6건을 잠그고 B가 끝날 때까지 커밋하지 않는다.
        CompletableFuture<Void> instanceA = CompletableFuture.runAsync(() -> transactionTemplate.executeWithoutResult(status -> {
            List<AccountOutboxEvent> mine = outboxRepository.lockPublishable(now, 6);
            mine.forEach(event -> event.claimUntil(leaseUntil));
            mine.forEach(event -> first.add(event.getId()));
            locked.countDown();
            try {
                otherDone.await(10, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        }));
        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();

        // 인스턴스 B: 같은 시각에 10건을 요청해도 A가 잠근 행을 건너뛰고 즉시 나머지 4건만 받는다.
        long started = System.nanoTime();
        List<Long> second = claimService.claim(now, leaseUntil, 10);
        long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        otherDone.countDown();
        instanceA.get(10, TimeUnit.SECONDS);

        assertThat(first).hasSize(6);
        assertThat(second).hasSize(4).doesNotContainAnyElementsOf(first);
        assertThat(elapsedMillis).isLessThan(5_000);

        // 둘 다 선점했으므로 만료 전에는 아무도 다시 받지 못한다.
        assertThat(claimService.claim(now.plusSeconds(60), leaseUntil.plusSeconds(60), 10)).isEmpty();
        // 선점이 만료되면(발행하지 못하고 중단된 경우) 다시 발행 대상이 된다.
        assertThat(claimService.claim(leaseUntil.plusSeconds(1), leaseUntil.plusSeconds(121), 10)).hasSize(10);
    }
}
