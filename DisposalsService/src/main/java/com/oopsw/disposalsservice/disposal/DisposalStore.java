package com.oopsw.disposalsservice.disposal;
import com.oopsw.disposalsservice.api.*;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly=true)
public class DisposalStore {
    private final DisposalRepository repository;
    private final StockClient stock;
    @Transactional
    public DisposalController.View register(long accountId,DisposalController.Create request) {
        var record=repository.findByAccountIdAndRequestId(accountId,request.requestId().trim())
            .orElseGet(()->repository.saveAndFlush(Disposal.create(accountId,request)));
        return matched(record,request);
    }
    public DisposalController.View existing(long accountId,DisposalController.Create request) {
        return matched(repository.findByAccountIdAndRequestId(accountId,request.requestId().trim())
            .orElseThrow(()->new ApiException(ApiErrorCode.REQUEST_CONFLICT)),request);
    }
    private DisposalController.View matched(Disposal record,DisposalController.Create request) {
        if(!Objects.equals(record.getFoodMaterialId(),request.foodMaterialId()) || !Objects.equals(record.getQuantity(),request.quantity())
            || !record.getReason().equals(request.reason().trim())) throw new ApiException(ApiErrorCode.REQUEST_CONFLICT);
        return DisposalController.View.of(record);
    }
    public DisposalController.View get(long accountId,String id) {
        return DisposalController.View.of(repository.findByIdAndAccountId(id,accountId)
            .orElseThrow(()->new ApiException(ApiErrorCode.DISPOSAL_NOT_FOUND)));
    }
    public DisposalController.ListView list(long accountId,Disposal.Status status,int page,int size) {
        var pageable=PageRequest.of(page,size,Sort.by(Sort.Direction.DESC,"createdAt","id"));
        var result=(status==null?repository.findAllByAccountId(accountId,pageable):repository.findAllByAccountIdAndStatus(accountId,status,pageable)).map(DisposalController.View::of);
        return new DisposalController.ListView(result.getContent(),page,size,result.getTotalElements(),result.getTotalPages());
    }
    @Transactional
    public DisposalController.View process(long accountId,String id,String authorization) {
        var record=repository.lockOwned(id,accountId).orElseThrow(()->new ApiException(ApiErrorCode.DISPOSAL_NOT_FOUND));
        // Serialize attempts for one request, including the bounded HTTP call.
        if(record.getStatus()==Disposal.Status.PENDING) {
            var result=stock.dispose(DisposalController.View.of(record),authorization);
            if(result.applied()) record.complete(result.movementId(),result.quantityAfter());
            else if(result.rejectionCode()!=null) record.reject(result.rejectionCode());
        }
        return DisposalController.View.of(repository.saveAndFlush(record));
    }
}
