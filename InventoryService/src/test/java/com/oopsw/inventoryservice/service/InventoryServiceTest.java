package com.oopsw.inventoryservice.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.oopsw.inventoryservice.api.ApiErrorCode;
import com.oopsw.inventoryservice.api.ApiException;
import com.oopsw.inventoryservice.domain.InventoryEntity;
import com.oopsw.inventoryservice.domain.InventoryRepository;
import com.oopsw.inventoryservice.domain.StockMovementEntity;
import com.oopsw.inventoryservice.domain.StockMovementRepository;
import com.oopsw.inventoryservice.web.dto.AdjustInventoryRequest;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class InventoryServiceTest {

    @Mock
    private InventoryRepository inventoryRepository;

    @Mock
    private StockMovementRepository movementRepository;

    private InventoryService inventoryService;

    @BeforeEach
    void setUp() {
        inventoryService = new InventoryService(
            inventoryRepository,
            movementRepository
        );
    }

    @Test
    void 초기재고와_원장을_함께_생성한다() {
        when(inventoryRepository.existsByAccountIdAndItemId(10L, 100L))
            .thenReturn(false);
        when(inventoryRepository.saveAndFlush(any(InventoryEntity.class)))
            .thenAnswer(invocation -> persistedInventory(
                invocation.getArgument(0),
                1L,
                0L
            ));
        when(movementRepository.saveAndFlush(any(StockMovementEntity.class)))
            .thenAnswer(invocation -> invocation.getArgument(0));

        var response = inventoryService.create(10L, 100L, 30L);

        assertThat(response.itemId()).isEqualTo(100L);
        assertThat(response.onHandQuantity()).isEqualTo(30L);
        assertThat(response.version()).isZero();
        verify(movementRepository).saveAndFlush(any(StockMovementEntity.class));
    }

    @Test
    void 이미_재고가_있으면_중복생성을_거절한다() {
        when(inventoryRepository.existsByAccountIdAndItemId(10L, 100L))
            .thenReturn(true);

        assertError(
            () -> inventoryService.create(10L, 100L, 30L),
            ApiErrorCode.INVENTORY_ALREADY_EXISTS
        );
    }

    @Test
    void 재고수량을_변경하고_원장을_기록한다() {
        InventoryEntity inventory = inventory(10L, 100L, 30L, 1L, 0L);
        when(inventoryRepository.findByAccountIdAndItemId(10L, 100L))
            .thenReturn(Optional.of(inventory));
        when(movementRepository.existsByAccountIdAndRequestId(
            10L,
            "ADJ-001"
        )).thenReturn(false);
        when(inventoryRepository.saveAndFlush(inventory))
            .thenAnswer(invocation -> persistedInventory(
                inventory,
                1L,
                1L
            ));
        when(movementRepository.saveAndFlush(any(StockMovementEntity.class)))
            .thenAnswer(invocation -> {
                StockMovementEntity movement = invocation.getArgument(0);
                ReflectionTestUtils.setField(movement, "id", 5L);
                return movement;
            });

        var response = inventoryService.adjust(
            10L,
            100L,
            adjustment("ADJ-001", -5L, 0L)
        );

        assertThat(response.inventory().onHandQuantity()).isEqualTo(25L);
        assertThat(response.inventory().version()).isEqualTo(1L);
        assertThat(response.movement().quantityBefore()).isEqualTo(30L);
        assertThat(response.movement().quantityAfter()).isEqualTo(25L);
        assertThat(response.movement().quantityDelta()).isEqualTo(-5L);
    }

    @Test
    void 재고보다_많이_차감하면_거절한다() {
        InventoryEntity inventory = inventory(10L, 100L, 3L, 1L, 0L);
        when(inventoryRepository.findByAccountIdAndItemId(10L, 100L))
            .thenReturn(Optional.of(inventory));

        assertError(
            () -> inventoryService.adjust(
                10L,
                100L,
                adjustment("ADJ-001", -4L, 0L)
            ),
            ApiErrorCode.INSUFFICIENT_STOCK
        );
        assertThat(inventory.getOnHandQuantity()).isEqualTo(3L);
    }

    @Test
    void 오래된_버전으로_변경하면_충돌을_반환한다() {
        InventoryEntity inventory = inventory(10L, 100L, 30L, 1L, 2L);
        when(inventoryRepository.findByAccountIdAndItemId(10L, 100L))
            .thenReturn(Optional.of(inventory));

        assertError(
            () -> inventoryService.adjust(
                10L,
                100L,
                adjustment("ADJ-001", 5L, 1L)
            ),
            ApiErrorCode.INVENTORY_CONFLICT
        );
    }

    @Test
    void 같은_변경요청_ID는_다시_처리하지_않는다() {
        when(movementRepository.existsByAccountIdAndRequestId(
            10L,
            "ADJ-001"
        )).thenReturn(true);

        assertError(
            () -> inventoryService.adjust(
                10L,
                100L,
                adjustment("ADJ-001", 5L, 0L)
            ),
            ApiErrorCode.ADJUSTMENT_ALREADY_EXISTS
        );
    }

    @Test
    void 다른_계정의_재고는_조회할_수_없다() {
        when(inventoryRepository.findByAccountIdAndItemId(20L, 100L))
            .thenReturn(Optional.empty());

        assertError(
            () -> inventoryService.get(20L, 100L),
            ApiErrorCode.INVENTORY_NOT_FOUND
        );
    }

    @Test
    void 수량변경이_0이면_거절한다() {
        assertError(
            () -> inventoryService.adjust(
                10L,
                100L,
                adjustment("ADJ-001", 0L, 0L)
            ),
            ApiErrorCode.INVALID_REQUEST
        );
    }

    private AdjustInventoryRequest adjustment(
        String requestId,
        Long delta,
        Long version
    ) {
        return new AdjustInventoryRequest(
            requestId,
            delta,
            "테스트 조정",
            version
        );
    }

    private InventoryEntity inventory(
        Long accountId,
        Long itemId,
        Long quantity,
        Long id,
        Long version
    ) {
        return persistedInventory(
            InventoryEntity.create(accountId, itemId, quantity),
            id,
            version
        );
    }

    private InventoryEntity persistedInventory(
        InventoryEntity inventory,
        Long id,
        Long version
    ) {
        ReflectionTestUtils.setField(inventory, "id", id);
        ReflectionTestUtils.setField(inventory, "version", version);
        return inventory;
    }

    private void assertError(Runnable action, ApiErrorCode errorCode) {
        assertThatThrownBy(action::run)
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(errorCode);
    }
}
