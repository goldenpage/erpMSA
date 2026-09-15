package com.oopsw.foodmaterialsservice.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.oopsw.foodmaterialsservice.api.ApiErrorCode;
import com.oopsw.foodmaterialsservice.api.ApiException;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialEntity;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialRepository;
import com.oopsw.foodmaterialsservice.domain.FoodMaterialStatus;
import com.oopsw.foodmaterialsservice.web.dto.CreateFoodMaterialRequest;
import com.oopsw.foodmaterialsservice.web.dto.UpdateFoodMaterialRequest;
import java.math.BigDecimal;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class FoodMaterialsServiceTest {

    @Mock
    private FoodMaterialRepository itemRepository;

    private FoodMaterialsService foodMaterialsService;

    @BeforeEach
    void setUp() {
        foodMaterialsService = new FoodMaterialsService(itemRepository);
    }

    @Test
    void 품목을_등록할_때_SKU를_정규화한다() {
        when(itemRepository.existsByAccountIdAndSku(10L, "SKU-001"))
            .thenReturn(false);
        when(itemRepository.saveAndFlush(any(FoodMaterialEntity.class)))
            .thenAnswer(invocation -> invocation.getArgument(0));

        var response = foodMaterialsService.create(
            10L,
            new CreateFoodMaterialRequest(
                " sku-001 ",
                " 테스트 품목 ",
                " 설명 ",
                new BigDecimal("1200.00")
            )
        );

        assertThat(response.sku()).isEqualTo("SKU-001");
        assertThat(response.name()).isEqualTo("테스트 품목");
        assertThat(response.description()).isEqualTo("설명");
        assertThat(response.status()).isEqualTo(FoodMaterialStatus.ACTIVE);
        verify(itemRepository).saveAndFlush(any(FoodMaterialEntity.class));
    }

    @Test
    void 같은_계정에_SKU가_중복되면_거절한다() {
        when(itemRepository.existsByAccountIdAndSku(10L, "SKU-001"))
            .thenReturn(true);

        assertThatThrownBy(() -> foodMaterialsService.create(
            10L,
            new CreateFoodMaterialRequest(
                "sku-001",
                "테스트 품목",
                null,
                BigDecimal.ZERO
            )
        ))
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(ApiErrorCode.SKU_ALREADY_EXISTS);
    }

    @Test
    void 다른_계정의_품목은_조회할_수_없다() {
        when(itemRepository.findByIdAndAccountId(1L, 20L))
            .thenReturn(Optional.empty());

        assertThatThrownBy(() -> foodMaterialsService.get(20L, 1L))
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(ApiErrorCode.FOOD_MATERIAL_NOT_FOUND);
    }

    @Test
    void 삭제는_데이터를_지우지_않고_비활성화한다() {
        FoodMaterialEntity item = FoodMaterialEntity.create(
            10L,
            "SKU-001",
            "테스트 품목",
            null,
            BigDecimal.TEN
        );
        ReflectionTestUtils.setField(item, "version", 0L);
        when(itemRepository.findByIdAndAccountId(1L, 10L))
            .thenReturn(Optional.of(item));
        when(itemRepository.saveAndFlush(item)).thenReturn(item);

        foodMaterialsService.deactivate(10L, 1L);

        assertThat(item.getStatus()).isEqualTo(FoodMaterialStatus.INACTIVE);
        verify(itemRepository).saveAndFlush(item);
    }

    @Test
    void 품목을_수정한다() {
        FoodMaterialEntity item = FoodMaterialEntity.create(
            10L,
            "SKU-001",
            "기존 이름",
            null,
            BigDecimal.TEN
        );
        ReflectionTestUtils.setField(item, "version", 0L);
        when(itemRepository.findByIdAndAccountId(1L, 10L))
            .thenReturn(Optional.of(item));
        when(itemRepository.saveAndFlush(item)).thenReturn(item);

        var response = foodMaterialsService.update(
            10L,
            1L,
            new UpdateFoodMaterialRequest(
                " 수정 이름 ",
                " ",
                new BigDecimal("99.90"),
                FoodMaterialStatus.INACTIVE,
                0L
            )
        );

        assertThat(response.name()).isEqualTo("수정 이름");
        assertThat(response.description()).isNull();
        assertThat(response.unitPrice()).isEqualByComparingTo("99.90");
        assertThat(response.status()).isEqualTo(FoodMaterialStatus.INACTIVE);
    }

    @Test
    void 오래된_버전으로_수정하면_충돌을_반환한다() {
        FoodMaterialEntity item = FoodMaterialEntity.create(
            10L,
            "SKU-001",
            "기존 이름",
            null,
            BigDecimal.TEN
        );
        ReflectionTestUtils.setField(item, "version", 3L);
        when(itemRepository.findByIdAndAccountId(1L, 10L))
            .thenReturn(Optional.of(item));

        assertThatThrownBy(() -> foodMaterialsService.update(
            10L,
            1L,
            new UpdateFoodMaterialRequest(
                "수정 이름",
                null,
                BigDecimal.ONE,
                FoodMaterialStatus.ACTIVE,
                2L
            )
        ))
            .isInstanceOf(ApiException.class)
            .extracting(exception -> ((ApiException) exception).errorCode())
            .isEqualTo(ApiErrorCode.FOOD_MATERIAL_CONFLICT);
    }
}
