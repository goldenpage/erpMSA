package com.oopsw.disposalsservice.disposal;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/disposals")
@RequiredArgsConstructor
public class DisposalController {
    private final DisposalService service;
    private final DisposalStore store;
    public record Create(@NotBlank @Size(max=64) String requestId,@NotNull @Positive Long foodMaterialId,
        @NotNull @Positive Long quantity,@NotBlank @Size(max=255) String reason) {}
    public record View(String disposalId,String requestId,Long foodMaterialId,Long quantity,String reason,
        Disposal.Status status,Long movementId,Long quantityAfter,String rejectionCode,Instant createdAt,Instant updatedAt) {
        public static View of(Disposal d) {return new View(d.getId(),d.getRequestId(),d.getFoodMaterialId(),d.getQuantity(),d.getReason(),d.getStatus(),d.getMovementId(),d.getQuantityAfter(),d.getRejectionCode(),d.getCreatedAt(),d.getUpdatedAt());}
    }
    public record ListView(List<View> disposals,int page,int size,long totalElements,int totalPages) {}
    @PostMapping
    public ResponseEntity<View> create(@RequestAttribute("accountId") long accountId,@Valid @RequestBody Create request,
        @RequestHeader(HttpHeaders.AUTHORIZATION) String authorization) {return response(service.create(accountId,request,authorization));}
    @PostMapping("/{disposalId}/retry")
    public ResponseEntity<View> retry(@RequestAttribute("accountId") long accountId,@PathVariable String disposalId,
        @RequestHeader(HttpHeaders.AUTHORIZATION) String authorization) {return response(service.retry(accountId,disposalId,authorization));}
    @GetMapping("/{disposalId}")
    public View get(@RequestAttribute("accountId") long accountId,@PathVariable String disposalId) {return store.get(accountId,disposalId);}
    @GetMapping
    public ListView list(@RequestAttribute("accountId") long accountId,@RequestParam(required=false) Disposal.Status status,
        @RequestParam(defaultValue="0") @Min(0) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size) {return store.list(accountId,status,page,size);}
    private ResponseEntity<View> response(View result) {
        int status=switch(result.status()) {case COMPLETED->200;case PENDING->202;case REJECTED->409;};
        return ResponseEntity.status(status).location(URI.create("/disposals/"+result.disposalId())).body(result);
    }
}
