package com.oopsw.gatewayserver;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.gatewayserver.api.ApiErrorWriter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@org.junit.jupiter.api.Tag("unit")
class RouteInFlightLimitFilterTest {

    private static final FilterChain OK = (request, response) -> ((HttpServletResponse) response).setStatus(200);

    private ObjectMapper objectMapper;
    private SimpleMeterRegistry registry;
    private RouteInFlightLimitFilter filter;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        registry = new SimpleMeterRegistry();
        filter = new RouteInFlightLimitFilter(new ApiErrorWriter(objectMapper), registry,
            new String[] {"account", "menus"}, 2);
    }

    @Test
    void 경로_구간을_추출한다() {
        assertThat(RouteInFlightLimitFilter.routeOf("/account/auth/login")).isEqualTo("account");
        assertThat(RouteInFlightLimitFilter.routeOf("/menus")).isEqualTo("menus");
        assertThat(RouteInFlightLimitFilter.routeOf("/")).isNull();
        assertThat(RouteInFlightLimitFilter.routeOf("")).isNull();
    }

    @Test
    void 상한을_넘는_동시_요청은_즉시_503으로_거절하고_다른_경로는_통과시킨다() throws Exception {
        CountDownLatch entered = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        FilterChain blocking = (request, response) -> {
            entered.countDown();
            try {
                release.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        };
        ExecutorService executor = Executors.newFixedThreadPool(2);
        try {
            Future<?> first = executor.submit(() -> invoke("/account/auth/login", blocking));
            Future<?> second = executor.submit(() -> invoke("/account/auth/login", blocking));
            assertThat(entered.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(registry.get("gateway.route.in.flight").tag("route", "account").gauge().value()).isEqualTo(2.0);

            MockHttpServletResponse rejected = invoke("/account/auth/me", (request, response) -> { });
            assertThat(rejected.getStatus()).isEqualTo(503);
            assertThat(rejected.getHeader("Retry-After")).isEqualTo("1");
            JsonNode body = objectMapper.readTree(rejected.getContentAsString(StandardCharsets.UTF_8));
            assertThat(body.get("code").asString()).isEqualTo("ROUTE_BUSY");
            assertThat(registry.get("gateway.route.rejected").tag("route", "account").counter().count()).isEqualTo(1.0);

            MockHttpServletResponse other = invoke("/menus", OK);
            assertThat(other.getStatus()).isEqualTo(200);

            release.countDown();
            first.get(5, TimeUnit.SECONDS);
            second.get(5, TimeUnit.SECONDS);
        } finally {
            release.countDown();
            executor.shutdownNow();
        }
        assertThat(registry.get("gateway.route.in.flight").tag("route", "account").gauge().value()).isZero();
        assertThat(invoke("/account/auth/me", OK).getStatus()).isEqualTo(200);
    }

    @Test
    void 하류_처리에서_예외가_나도_허가를_반환한다() throws Exception {
        FilterChain failing = (request, response) -> {
            throw new IllegalStateException("downstream failure");
        };
        for (int i = 0; i < 3; i++) {
            try {
                invoke("/account/auth/login", failing);
            } catch (IllegalStateException expected) {
                // 다음 반복에서도 허가를 얻을 수 있어야 한다.
            }
        }
        assertThat(registry.get("gateway.route.in.flight").tag("route", "account").gauge().value()).isZero();
    }

    @Test
    void 제한_대상이_아닌_경로는_세지_않는다() throws Exception {
        assertThat(invoke("/actuator/health", OK).getStatus()).isEqualTo(200);
        assertThat(registry.find("gateway.route.in.flight").tag("route", "actuator").gauge()).isNull();
    }

    private MockHttpServletResponse invoke(String path, FilterChain chain) {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", path);
        request.setRequestURI(path);
        MockHttpServletResponse response = new MockHttpServletResponse();
        try {
            filter.doFilter(request, response, chain);
        } catch (RuntimeException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
        return response;
    }
}
