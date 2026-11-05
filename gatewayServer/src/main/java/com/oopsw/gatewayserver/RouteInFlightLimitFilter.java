package com.oopsw.gatewayserver;

import com.oopsw.gatewayserver.api.ApiErrorCode;
import com.oopsw.gatewayserver.api.ApiErrorWriter;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Semaphore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 경로(첫 번째 경로 구간)별 동시 처리 요청 수를 제한한다.
 *
 * <p>하류 서비스가 느려지면 Gateway에 처리 중인 요청이 쌓여 메모리 한계를 넘을 수 있다
 * (docs/account-load-results.md 발견 1). 상한을 넘는 요청은 기다리지 않고 503으로 즉시 거절해
 * 한 서비스의 과부하가 다른 경로와 Gateway 프로세스로 번지지 않게 한다.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class RouteInFlightLimitFilter extends OncePerRequestFilter {

    static final String RETRY_AFTER_SECONDS = "1";

    private final Map<String, Semaphore> limits = new HashMap<>();
    private final Map<String, Counter> rejected = new HashMap<>();
    private final ApiErrorWriter apiErrorWriter;

    public RouteInFlightLimitFilter(
        ApiErrorWriter apiErrorWriter,
        MeterRegistry registry,
        @Value("${app.gateway.in-flight.routes:account,menus,foodmaterials,notices,bills,purchase,disposals}") String[] routes,
        @Value("${app.gateway.in-flight.max-per-route:50}") int maxPerRoute
    ) {
        if (maxPerRoute < 1) {
            throw new IllegalArgumentException("app.gateway.in-flight.max-per-route must be positive");
        }
        this.apiErrorWriter = apiErrorWriter;
        for (String route : routes) {
            Semaphore semaphore = new Semaphore(maxPerRoute);
            limits.put(route, semaphore);
            Gauge.builder("gateway.route.in.flight", semaphore, s -> maxPerRoute - s.availablePermits())
                .tag("route", route).description("Gateway에서 처리 중인 요청 수").register(registry);
            Gauge.builder("gateway.route.in.flight.limit", () -> maxPerRoute)
                .tag("route", route).register(registry);
            rejected.put(route, Counter.builder("gateway.route.rejected")
                .tag("route", route).description("동시 처리 상한 초과로 거절한 요청 수").register(registry));
        }
    }

    static String routeOf(String path) {
        if (path == null || path.length() < 2 || path.charAt(0) != '/') {
            return null;
        }
        int end = path.indexOf('/', 1);
        return end < 0 ? path.substring(1) : path.substring(1, end);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !limits.containsKey(routeOf(request.getRequestURI()));
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {
        String route = routeOf(request.getRequestURI());
        Semaphore semaphore = limits.get(route);
        if (!semaphore.tryAcquire()) {
            rejected.get(route).increment();
            response.setHeader(HttpHeaders.RETRY_AFTER, RETRY_AFTER_SECONDS);
            apiErrorWriter.write(request, response, ApiErrorCode.ROUTE_BUSY);
            return;
        }
        try {
            filterChain.doFilter(request, response);
        } finally {
            semaphore.release();
        }
    }
}
