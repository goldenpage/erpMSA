package com.oopsw.disposalsservice.disposal;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

@Entity
@Table(name="disposal",uniqueConstraints=@UniqueConstraint(name="uk_disposal_account_request",columnNames={"account_id","request_id"}))
@Getter
@NoArgsConstructor(access=lombok.AccessLevel.PROTECTED)
public class Disposal {
    @Id @Column(length=36) private String id;
    @Column(nullable=false) private Long accountId;
    @Column(nullable=false,length=64) private String requestId;
    @Column(nullable=false) private Long foodMaterialId;
    @Column(nullable=false) private Long quantity;
    @Column(nullable=false,length=255) private String reason;
    @Enumerated(EnumType.STRING) @Column(nullable=false,length=20) private Status status;
    private Long movementId;
    private Long quantityAfter;
    @Column(length=64) private String rejectionCode;
    @Version @Column(nullable=false) private Long version;
    @CreationTimestamp @Column(nullable=false,updatable=false) private Instant createdAt;
    @UpdateTimestamp @Column(nullable=false) private Instant updatedAt;
    public enum Status { PENDING, COMPLETED, REJECTED }
    public static Disposal create(long accountId,DisposalController.Create request) {
        var value=new Disposal();value.id=UUID.randomUUID().toString();value.accountId=accountId;
        value.requestId=request.requestId().trim();value.foodMaterialId=request.foodMaterialId();
        value.quantity=request.quantity();value.reason=request.reason().trim();value.status=Status.PENDING;
        return value;
    }
    public void complete(long movementId,long quantityAfter) {
        status=Status.COMPLETED;this.movementId=movementId;this.quantityAfter=quantityAfter;rejectionCode=null;
    }
    public void reject(String code) { status=Status.REJECTED;rejectionCode=code; }
}
