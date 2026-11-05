package com.oopsw.accountservice.outbox;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

@org.junit.jupiter.api.Tag("unit")
class OutboxPublisherTest {

    private static final Instant NOW = Instant.parse("2026-11-04T00:00:00Z");

    /** instant()를 호출할 때마다 정해진 시각을 차례로 돌려주는 시계. */
    static final class StepClock extends Clock {
        private final Instant[] instants;
        private int index;
        StepClock(Instant... instants) { this.instants = instants; }
        @Override public Instant instant() { return instants[Math.min(index++, instants.length - 1)]; }
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
    }

    @Test
    void 선점한_이벤트를_순서대로_발행하고_선점_만료시각으로_선점한다() {
        OutboxClaimService claims = mock(OutboxClaimService.class);
        OutboxPublicationService publication = mock(OutboxPublicationService.class);
        when(claims.claim(eq(NOW), eq(NOW.plusSeconds(120)), eq(100))).thenReturn(List.of(3L, 1L, 2L));
        OutboxPublisher publisher = new OutboxPublisher(claims, publication, new StepClock(NOW),
            Duration.ofSeconds(120), Duration.ofSeconds(30), 100);

        publisher.publishPendingEvents();

        InOrder order = inOrder(publication);
        order.verify(publication).publish(3L);
        order.verify(publication).publish(1L);
        order.verify(publication).publish(2L);
    }

    @Test
    void 선점_만료가_가까우면_남은_이벤트를_발행하지_않는다() {
        OutboxClaimService claims = mock(OutboxClaimService.class);
        OutboxPublicationService publication = mock(OutboxPublicationService.class);
        when(claims.claim(any(), any(), eq(100))).thenReturn(List.of(1L, 2L, 3L));
        // 첫 발행 뒤 시계가 만료 30초 전(90초 경과)에 도달한다.
        OutboxPublisher publisher = new OutboxPublisher(claims, publication,
            new StepClock(NOW, NOW.plusSeconds(1), NOW.plusSeconds(90)), Duration.ofSeconds(120), Duration.ofSeconds(30), 100);

        publisher.publishPendingEvents();

        verify(publication).publish(1L);
        verify(publication, never()).publish(2L);
        verify(publication, never()).publish(3L);
    }

    @Test
    void 선점_기간은_안전_여유보다_길어야_한다() {
        assertThatThrownBy(() -> new OutboxPublisher(mock(OutboxClaimService.class), mock(OutboxPublicationService.class),
            Clock.systemUTC(), Duration.ofSeconds(30), Duration.ofSeconds(30), 100))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
