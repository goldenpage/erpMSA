package com.oopsw.inventoryservice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;
import org.hibernate.annotations.CreationTimestamp;

@Entity
@Table(
    name = "stock_movement",
    uniqueConstraints = @UniqueConstraint(
        name = "uk_movement_account_request",
        columnNames = {"account_id", "request_id"}
    )
)
public class StockMovementEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "inventory_id", nullable = false)
    private Long inventoryId;

    @Column(name = "account_id", nullable = false)
    private Long accountId;

    @Column(name = "item_id", nullable = false)
    private Long itemId;

    @Column(name = "request_id", nullable = false, length = 64)
    private String requestId;

    @Enumerated(EnumType.STRING)
    @Column(name = "movement_type", nullable = false, length = 20)
    private MovementType movementType;

    @Column(name = "quantity_delta", nullable = false)
    private Long quantityDelta;

    @Column(name = "quantity_before", nullable = false)
    private Long quantityBefore;

    @Column(name = "quantity_after", nullable = false)
    private Long quantityAfter;

    @Column(nullable = false, length = 255)
    private String reason;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected StockMovementEntity() {
    }

    public static StockMovementEntity initial(InventoryEntity inventory) {
        return create(
            inventory,
            "INITIAL:" + inventory.getItemId(),
            MovementType.INITIAL,
            inventory.getOnHandQuantity(),
            0L,
            inventory.getOnHandQuantity(),
            "초기 재고 등록"
        );
    }

    public static StockMovementEntity adjustment(
        InventoryEntity inventory,
        String requestId,
        Long quantityDelta,
        InventoryEntity.QuantityChange change,
        String reason
    ) {
        return create(
            inventory,
            requestId,
            MovementType.ADJUSTMENT,
            quantityDelta,
            change.before(),
            change.after(),
            reason
        );
    }

    private static StockMovementEntity create(
        InventoryEntity inventory,
        String requestId,
        MovementType type,
        Long quantityDelta,
        Long quantityBefore,
        Long quantityAfter,
        String reason
    ) {
        StockMovementEntity movement = new StockMovementEntity();
        movement.inventoryId = inventory.getId();
        movement.accountId = inventory.getAccountId();
        movement.itemId = inventory.getItemId();
        movement.requestId = requestId;
        movement.movementType = type;
        movement.quantityDelta = quantityDelta;
        movement.quantityBefore = quantityBefore;
        movement.quantityAfter = quantityAfter;
        movement.reason = reason;
        return movement;
    }

    public Long getId() {
        return id;
    }

    public Long getInventoryId() {
        return inventoryId;
    }

    public Long getAccountId() {
        return accountId;
    }

    public Long getItemId() {
        return itemId;
    }

    public String getRequestId() {
        return requestId;
    }

    public MovementType getMovementType() {
        return movementType;
    }

    public Long getQuantityDelta() {
        return quantityDelta;
    }

    public Long getQuantityBefore() {
        return quantityBefore;
    }

    public Long getQuantityAfter() {
        return quantityAfter;
    }

    public String getReason() {
        return reason;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
