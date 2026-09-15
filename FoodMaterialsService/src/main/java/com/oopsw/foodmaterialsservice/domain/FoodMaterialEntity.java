package com.oopsw.foodmaterialsservice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;
import java.math.BigDecimal;
import java.time.Instant;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

@Entity
@Table(
    name = "item",
    uniqueConstraints = @UniqueConstraint(
        name = "uk_item_account_sku",
        columnNames = {"account_id", "sku"}
    )
)
public class FoodMaterialEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "account_id", nullable = false)
    private Long accountId;

    @Column(nullable = false, length = 64)
    private String sku;

    @Column(nullable = false, length = 100)
    private String name;

    @Column(length = 1000)
    private String description;

    @Column(name = "unit_price", nullable = false, precision = 15, scale = 2)
    private BigDecimal unitPrice;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private FoodMaterialStatus status;

    @Version
    @Column(nullable = false)
    private Long version;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected FoodMaterialEntity() {
    }

    public static FoodMaterialEntity create(
        Long accountId,
        String sku,
        String name,
        String description,
        BigDecimal unitPrice
    ) {
        FoodMaterialEntity item = new FoodMaterialEntity();
        item.accountId = accountId;
        item.sku = sku;
        item.name = name;
        item.description = description;
        item.unitPrice = unitPrice;
        item.status = FoodMaterialStatus.ACTIVE;
        return item;
    }

    public void update(
        String name,
        String description,
        BigDecimal unitPrice,
        FoodMaterialStatus status
    ) {
        this.name = name;
        this.description = description;
        this.unitPrice = unitPrice;
        this.status = status;
    }

    public void deactivate() {
        this.status = FoodMaterialStatus.INACTIVE;
    }

    public Long getId() {
        return id;
    }

    public Long getAccountId() {
        return accountId;
    }

    public String getSku() {
        return sku;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public BigDecimal getUnitPrice() {
        return unitPrice;
    }

    public FoodMaterialStatus getStatus() {
        return status;
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
}
