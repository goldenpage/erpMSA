package com.oopsw.foodmaterialsservice.inventory.web;

import com.oopsw.foodmaterialsservice.auth.AuthenticatedAccount;
import com.oopsw.foodmaterialsservice.auth.JwtAuthenticationFilter;
import com.oopsw.foodmaterialsservice.inventory.service.InventoryRegistrationService;
import com.oopsw.foodmaterialsservice.inventory.service.InventoryService;
import com.oopsw.foodmaterialsservice.inventory.web.dto.AdjustInventoryRequest;
import com.oopsw.foodmaterialsservice.inventory.web.dto.CreateInventoryRequest;
import com.oopsw.foodmaterialsservice.inventory.web.dto.InventoryAdjustmentResponse;
import com.oopsw.foodmaterialsservice.inventory.web.dto.InventoryPageResponse;
import com.oopsw.foodmaterialsservice.inventory.web.dto.InventoryResponse;
import com.oopsw.foodmaterialsservice.inventory.web.dto.StockMovementPageResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Positive;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/foodmaterials/inventories")
@RequiredArgsConstructor
public class InventoryController {

    private final InventoryRegistrationService registrationService;
    private final InventoryService inventoryService;

    @PostMapping
    public ResponseEntity<InventoryResponse> create(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @Valid @RequestBody CreateInventoryRequest request
    ) {
        InventoryResponse response = registrationService.create(
            account.accountId(),
            request
        );
        return ResponseEntity.created(
            URI.create("/foodmaterials/inventories/" + response.foodMaterialId())
        ).body(response);
    }

    @GetMapping("/{foodMaterialId}")
    public InventoryResponse get(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId
    ) {
        return inventoryService.get(account.accountId(), foodMaterialId);
    }

    @GetMapping
    public InventoryPageResponse list(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @RequestParam(defaultValue = "0") @Min(0) int page,
        @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return inventoryService.list(account.accountId(), page, size);
    }

    @PostMapping("/{foodMaterialId}/adjustments")
    public InventoryAdjustmentResponse adjust(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId,
        @Valid @RequestBody AdjustInventoryRequest request
    ) {
        return inventoryService.adjust(account.accountId(), foodMaterialId, request);
    }

    @GetMapping("/{foodMaterialId}/movements")
    public StockMovementPageResponse movements(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId,
        @RequestParam(defaultValue = "0") @Min(0) int page,
        @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return inventoryService.movements(
            account.accountId(),
            foodMaterialId,
            page,
            size
        );
    }
}
