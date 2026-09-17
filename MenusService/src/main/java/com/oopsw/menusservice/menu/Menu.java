package com.oopsw.menusservice.menu;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

@Entity
@Table(name = "menu")
@Getter
@NoArgsConstructor(access = lombok.AccessLevel.PROTECTED)
public class Menu {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(nullable=false) private Long accountId;
    @Column(nullable=false,length=100) private String name;
    @Column(length=1000) private String description;
    @Column(nullable=false,precision=15,scale=2) private BigDecimal price;
    @Enumerated(EnumType.STRING) @Column(nullable=false,length=20) private Status status;
    @Version @Column(nullable=false) private Long version;
    @CreationTimestamp @Column(nullable=false,updatable=false) private Instant createdAt;
    @UpdateTimestamp @Column(nullable=false) private Instant updatedAt;
    public enum Status { ACTIVE, INACTIVE }

    public static Menu create(long accountId, MenuController.Create request) {
        var menu=new Menu(); menu.accountId=accountId;
        menu.update(request.name(),request.description(),request.price(),Status.ACTIVE);
        return menu;
    }
    public void update(String name,String description,BigDecimal price,Status status) {
        this.name=name.trim();this.description=description==null?null:description.trim();
        this.price=price;this.status=status;
    }
    public void deactivate() { status=Status.INACTIVE; }
}
