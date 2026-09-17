package com.oopsw.disposalsservice.disposal;
import java.util.Optional;
import org.springframework.data.domain.*;
import org.springframework.data.jpa.repository.*;
import jakarta.persistence.LockModeType;
public interface DisposalRepository extends JpaRepository<Disposal,String> {
    Optional<Disposal> findByAccountIdAndRequestId(long accountId,String requestId);
    Optional<Disposal> findByIdAndAccountId(String id,long accountId);
    Page<Disposal> findAllByAccountId(long accountId,Pageable pageable);
    Page<Disposal> findAllByAccountIdAndStatus(long accountId,Disposal.Status status,Pageable pageable);
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select d from Disposal d where d.id=:id and d.accountId=:accountId")
    Optional<Disposal> lockOwned(String id,long accountId);
}
