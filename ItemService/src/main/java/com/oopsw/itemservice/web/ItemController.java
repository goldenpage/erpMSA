package com.oopsw.itemservice.web;

import com.oopsw.itemservice.auth.AuthenticatedAccount;
import com.oopsw.itemservice.auth.JwtAuthenticationFilter;
import com.oopsw.itemservice.domain.ItemStatus;
import com.oopsw.itemservice.service.ItemService;
import com.oopsw.itemservice.web.dto.CreateItemRequest;
import com.oopsw.itemservice.web.dto.ItemPageResponse;
import com.oopsw.itemservice.web.dto.ItemResponse;
import com.oopsw.itemservice.web.dto.UpdateItemRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Positive;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/items")
@RequiredArgsConstructor
public class ItemController {

    private final ItemService itemService;

    @PostMapping
    public ResponseEntity<ItemResponse> create(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @Valid @RequestBody CreateItemRequest request
    ) {
        ItemResponse response = itemService.create(account.accountId(), request);
        return ResponseEntity.created(
            URI.create("/items/" + response.itemId())
        ).body(response);
    }

    @GetMapping("/{itemId}")
    public ItemResponse get(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId
    ) {
        return itemService.get(account.accountId(), itemId);
    }

    @GetMapping
    public ItemPageResponse list(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @RequestParam(required = false) ItemStatus status,
        @RequestParam(defaultValue = "0") @Min(0) int page,
        @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return itemService.list(account.accountId(), status, page, size);
    }

    @PutMapping("/{itemId}")
    public ItemResponse update(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId,
        @Valid @RequestBody UpdateItemRequest request
    ) {
        return itemService.update(account.accountId(), itemId, request);
    }

    @DeleteMapping("/{itemId}")
    public ResponseEntity<Void> deactivate(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long itemId
    ) {
        itemService.deactivate(account.accountId(), itemId);
        return ResponseEntity.noContent().build();
    }
}
