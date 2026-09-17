package com.oopsw.foodmaterialsservice.inventory.web;
import com.oopsw.foodmaterialsservice.auth.*;
import com.oopsw.foodmaterialsservice.inventory.service.InventoryDisposalService;
import com.oopsw.foodmaterialsservice.inventory.web.dto.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Positive;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class InventoryDisposalController {
    private final InventoryDisposalService service;
    @PostMapping("/foodmaterials/inventories/{foodMaterialId}/disposals")
    public StockMovementResponse dispose(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT) AuthenticatedAccount account,
        @PathVariable @Positive long foodMaterialId,@Valid @RequestBody DisposeInventoryRequest request
    ) { return service.dispose(account.accountId(),foodMaterialId,request); }
}
