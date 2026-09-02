package com.oopsw.inventoryservice.web;

import com.oopsw.inventoryservice.auth.AuthenticatedAccount;
import com.oopsw.inventoryservice.auth.JwtAuthenticationFilter;
import com.oopsw.inventoryservice.service.InventoryRegistrationService;
import com.oopsw.inventoryservice.service.InventoryService;
import com.oopsw.inventoryservice.web.dto.AdjustInventoryRequest;
import com.oopsw.inventoryservice.web.dto.CreateInventoryRequest;
import com.oopsw.inventoryservice.web.dto.InventoryAdjustmentResponse;
import com.oopsw.inventoryservice.web.dto.InventoryPageResponse;
import com.oopsw.inventoryservice.web.dto.InventoryResponse;
import com.oopsw.inventoryservice.web.dto.StockMovementPageResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Positive;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/inventories")
@RequiredArgsConstructor
public class InventoryController {

    private final InventoryRegistrationService registrationService;
    private final InventoryService inventoryService;

    @PostMapping
    public ResponseEntity<InventoryResponse> create(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @RequestHeader(HttpHeaders.AUTHORIZATION) String authorization,
        @Valid @RequestBody CreateInventoryRequest request
    ) {
        InventoryResponse response = registrationService.create(
            account.accountId(),
            authorization,
            request
        );
        return ResponseEntity.created(
            URI.create("/inventories/" + response.itemId())
        ).body(response);
    }

    @GetMapping("/{itemId}")
    public InventoryResponse get(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId
    ) {
        return inventoryService.get(account.accountId(), itemId);
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

    @PostMapping("/{itemId}/adjustments")
    public InventoryAdjustmentResponse adjust(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId,
        @Valid @RequestBody AdjustInventoryRequest request
    ) {
        return inventoryService.adjust(account.accountId(), itemId, request);
    }

    @GetMapping("/{itemId}/movements")
    public StockMovementPageResponse movements(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId,
        @RequestParam(defaultValue = "0") @Min(0) int page,
        @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return inventoryService.movements(
            account.accountId(),
            itemId,
            page,
            size
        );
    }
}
