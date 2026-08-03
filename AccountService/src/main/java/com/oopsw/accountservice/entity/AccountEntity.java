package com.oopsw.accountservice.entity;


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
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

@Getter
@Entity
@Table(name = "account",uniqueConstraints = {
    @UniqueConstraint(name  = "accountEmail", columnNames = "email"),
    @UniqueConstraint(name = "accountBusinessId", columnNames = "b_id")
})
@NoArgsConstructor
public class AccountEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 255)
    private String email;

    @Column(name = "b_id", nullable = false, length = 10)
    private String businessId;

    @Column(name="pwHash", nullable = false, length = 255)
    private String pwHash;


    private String username;


    private String documentPath;
    private String reason;
    private String ocrConfidence;
    private LocalDateTime reviewDate;





    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private AccountRole role;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private AccountStatus reviewStatus;

    @Column(nullable = false, length = 50)
    private String name;

    @Column(length = 20)
    private String phone;

    @Column(name = "store_name", nullable = false, length = 100)
    private String storeName;

    @Column(name = "store_type", length = 50)
    private String storeType;

    @Column(name = "store_category", length = 50)
    private String storeCategory;

    @Column(name = "marketing_agreed", nullable = false)
    private boolean marketingAgreed;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;


    public static AccountEntity register(
        String email,
        String businessId,
        String passwordHash,
        String name,
        String phone,
        String storeName,
        String storeType,
        String storeCategory,
        boolean marketingAgreed,
        AccountStatus status
    ) {
        AccountEntity account = new AccountEntity();

        account.email = email;
        account.businessId = businessId;
        account.pwHash = passwordHash;
        account.name = name;
        account.phone = phone;
        account.storeName = storeName;
        account.storeType = storeType;
        account.storeCategory = storeCategory;
        account.marketingAgreed = marketingAgreed;
        account.role = AccountRole.ROLE_USER;
        account.reviewStatus = status;

        return account;
    }

    public boolean canLogin() {
        return reviewStatus == AccountStatus.ACTIVE;
    }

    public void changeEmail(String normalizedEmail) {
        this.email = normalizedEmail;
    }
}
