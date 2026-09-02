package com.oopsw.inventoryservice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;
import java.time.Instant;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

@Entity
@Table(
    name = "inventory",
    uniqueConstraints = @UniqueConstraint(
        name = "uk_inventory_account_item",
        columnNames = {"account_id", "item_id"}
    )
)
public class InventoryEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "account_id", nullable = false)
    private Long accountId;

    @Column(name = "item_id", nullable = false)
    private Long itemId;

    @Column(name = "on_hand_quantity", nullable = false)
    private Long onHandQuantity;

    @Version
    @Column(nullable = false)
    private Long version;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected InventoryEntity() {
    }

    public static InventoryEntity create(
        Long accountId,
        Long itemId,
        Long initialQuantity
    ) {
        InventoryEntity inventory = new InventoryEntity();
        inventory.accountId = accountId;
        inventory.itemId = itemId;
        inventory.onHandQuantity = initialQuantity;
        return inventory;
    }

    public QuantityChange adjust(Long quantityDelta) {
        long before = onHandQuantity;
        long after = Math.addExact(before, quantityDelta);
        onHandQuantity = after;
        return new QuantityChange(before, after);
    }

    public Long getId() {
        return id;
    }

    public Long getAccountId() {
        return accountId;
    }

    public Long getItemId() {
        return itemId;
    }

    public Long getOnHandQuantity() {
        return onHandQuantity;
    }

    public Long getVersion() {
        return version;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public record QuantityChange(long before, long after) {
    }
}
