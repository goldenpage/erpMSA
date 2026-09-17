package com.oopsw.menusservice.menu;
import com.oopsw.menusservice.api.*;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly=true)
public class MenuService {
    private final MenuRepository repository;
    @Transactional
    public MenuController.View create(long accountId,MenuController.Create request) {
        return MenuController.View.of(repository.saveAndFlush(Menu.create(accountId,request)));
    }
    public MenuController.View get(long accountId,long id) { return MenuController.View.of(owned(accountId,id)); }
    public MenuController.ListView list(long accountId,Menu.Status status,int page,int size) {
        var pageable=PageRequest.of(page,size,Sort.by(Sort.Direction.DESC,"createdAt","id"));
        var result=(status==null?repository.findAllByAccountId(accountId,pageable):repository.findAllByAccountIdAndStatus(accountId,status,pageable)).map(MenuController.View::of);
        return new MenuController.ListView(result.getContent(),page,size,result.getTotalElements(),result.getTotalPages());
    }
    @Transactional
    public MenuController.View update(long accountId,long id,MenuController.Update request) {
        var menu=owned(accountId,id);
        if(!Objects.equals(menu.getVersion(),request.version())) throw new ApiException(ApiErrorCode.MENU_CONFLICT);
        menu.update(request.name(),request.description(),request.price(),request.status());
        return MenuController.View.of(repository.saveAndFlush(menu));
    }
    @Transactional
    public void deactivate(long accountId,long id) { var menu=owned(accountId,id);menu.deactivate();repository.saveAndFlush(menu); }
    private Menu owned(long accountId,long id) {
        return repository.findByIdAndAccountId(id,accountId).orElseThrow(()->new ApiException(ApiErrorCode.MENU_NOT_FOUND));
    }
}
