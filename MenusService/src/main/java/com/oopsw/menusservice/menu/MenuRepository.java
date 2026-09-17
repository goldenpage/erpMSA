package com.oopsw.menusservice.menu;
import java.util.Optional;
import org.springframework.data.domain.*;
import org.springframework.data.jpa.repository.JpaRepository;
public interface MenuRepository extends JpaRepository<Menu,Long> {
    Optional<Menu> findByIdAndAccountId(long id,long accountId);
    Page<Menu> findAllByAccountId(long accountId,Pageable pageable);
    Page<Menu> findAllByAccountIdAndStatus(long accountId,Menu.Status status,Pageable pageable);
}
