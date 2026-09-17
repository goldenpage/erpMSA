package com.oopsw.menusservice.menu;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/menus")
@RequiredArgsConstructor
public class MenuController {
    private final MenuService service;
    public record Create(@NotBlank @Size(max=100) String name,@Size(max=1000) String description,
        @NotNull @DecimalMin("0.00") @Digits(integer=13,fraction=2) BigDecimal price) {}
    public record Update(@NotBlank @Size(max=100) String name,@Size(max=1000) String description,
        @NotNull @DecimalMin("0.00") @Digits(integer=13,fraction=2) BigDecimal price,
        @NotNull Menu.Status status,@NotNull @PositiveOrZero Long version) {}
    public record View(Long menuId,String name,String description,BigDecimal price,Menu.Status status,Long version,Instant createdAt,Instant updatedAt) {
        static View of(Menu menu) { return new View(menu.getId(),menu.getName(),menu.getDescription(),menu.getPrice(),menu.getStatus(),menu.getVersion(),menu.getCreatedAt(),menu.getUpdatedAt()); }
    }
    public record ListView(List<View> menus,int page,int size,long totalElements,int totalPages) {}
    @PostMapping
    public ResponseEntity<View> create(@RequestAttribute("accountId") long accountId,@Valid @RequestBody Create request) {
        var result=service.create(accountId,request);return ResponseEntity.created(URI.create("/menus/"+result.menuId())).body(result);
    }
    @GetMapping("/{menuId}")
    public View get(@RequestAttribute("accountId") long accountId,@PathVariable @Positive long menuId) {return service.get(accountId,menuId);}
    @GetMapping
    public ListView list(@RequestAttribute("accountId") long accountId,@RequestParam(required=false) Menu.Status status,
        @RequestParam(defaultValue="0") @Min(0) int page,@RequestParam(defaultValue="20") @Min(1) @Max(100) int size) {return service.list(accountId,status,page,size);}
    @PutMapping("/{menuId}")
    public View update(@RequestAttribute("accountId") long accountId,@PathVariable @Positive long menuId,@Valid @RequestBody Update request) {return service.update(accountId,menuId,request);}
    @DeleteMapping("/{menuId}")
    public ResponseEntity<Void> deactivate(@RequestAttribute("accountId") long accountId,@PathVariable @Positive long menuId) {service.deactivate(accountId,menuId);return ResponseEntity.noContent().build();}
}
