package com.oopsw.foodmaterialsservice.web;

import com.oopsw.foodmaterialsservice.auth.AuthenticatedAccount;
import com.oopsw.foodmaterialsservice.auth.JwtAuthenticationFilter;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialStatus;
import com.oopsw.foodmaterialsservice.service.FoodMaterialsService;
import com.oopsw.foodmaterialsservice.web.dto.CreateFoodMaterialRequest;
import com.oopsw.foodmaterialsservice.web.dto.FoodMaterialPageResponse;
import com.oopsw.foodmaterialsservice.web.dto.FoodMaterialResponse;
import com.oopsw.foodmaterialsservice.web.dto.UpdateFoodMaterialRequest;
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
@RequestMapping("/foodmaterials")
@RequiredArgsConstructor
public class FoodMaterialController {

    private final FoodMaterialsService foodMaterialsService;

    @PostMapping
    public ResponseEntity<FoodMaterialResponse> create(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @Valid @RequestBody CreateFoodMaterialRequest request
    ) {
        FoodMaterialResponse response = foodMaterialsService.create(account.accountId(), request);
        return ResponseEntity.created(
            URI.create("/foodmaterials/" + response.foodMaterialId())
        ).body(response);
    }

    @GetMapping("/{foodMaterialId}")
    public FoodMaterialResponse get(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId
    ) {
        return foodMaterialsService.get(account.accountId(), foodMaterialId);
    }

    @GetMapping
    public FoodMaterialPageResponse list(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @RequestParam(required = false) FoodMaterialStatus status,
        @RequestParam(defaultValue = "0") @Min(0) int page,
        @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size
    ) {
        return foodMaterialsService.list(account.accountId(), status, page, size);
    }

    @PutMapping("/{foodMaterialId}")
    public FoodMaterialResponse update(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId,
        @Valid @RequestBody UpdateFoodMaterialRequest request
    ) {
        return foodMaterialsService.update(account.accountId(), foodMaterialId, request);
    }

    @DeleteMapping("/{foodMaterialId}")
    public ResponseEntity<Void> deactivate(
        @RequestAttribute(JwtAuthenticationFilter.AUTHENTICATED_ACCOUNT)
        AuthenticatedAccount account,
        @PathVariable @Positive Long foodMaterialId
    ) {
        foodMaterialsService.deactivate(account.accountId(), foodMaterialId);
        return ResponseEntity.noContent().build();
    }
}
