package com.oopsw.disposalsservice.disposal;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class DisposalService {
    private final DisposalStore store;
    public DisposalController.View create(long accountId,DisposalController.Create request,String authorization) {
        DisposalController.View record;
        try { record=store.register(accountId,request); }
        catch(DataIntegrityViolationException duplicate) { record=store.existing(accountId,request); }
        return attempt(accountId,record,authorization);
    }
    public DisposalController.View retry(long accountId,String id,String authorization) {
        return attempt(accountId,store.get(accountId,id),authorization);
    }
    private DisposalController.View attempt(long accountId,DisposalController.View record,String authorization) {
        if(record.status()!=Disposal.Status.PENDING) return record;
        return store.process(accountId,record.disposalId(),authorization);
    }
}
