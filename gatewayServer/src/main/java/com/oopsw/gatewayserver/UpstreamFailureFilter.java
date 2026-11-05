package com.oopsw.gatewayserver;

import com.oopsw.gatewayserver.api.ApiErrorCode;
import com.oopsw.gatewayserver.api.ApiErrorWriter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpTimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 하류 서비스 호출의 입출력 실패를 500 대신 의미 있는 응답으로 바꾼다.
 *
 * <ul>
 *   <li>연결 실패(주소 해석 실패, 연결 거부, 연결 시간 초과 등)나 고를 인스턴스가 없음: 503 {@code UPSTREAM_UNAVAILABLE} + Retry-After.
 *       재배포·장애로 인스턴스를 잠시 쓸 수 없다는 뜻이며 클라이언트가 다시 시도할 수 있다.</li>
 *   <li>응답 읽기 시간 초과: 504 {@code UPSTREAM_TIMEOUT}. 요청이 이미 처리됐을 수 있으므로 쓰기 요청은 그대로 재시도하면 안 된다.</li>
 * </ul>
 * 응답이 이미 나가기 시작했으면 바꿀 수 없으므로 예외를 그대로 둔다.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 5)
public class UpstreamFailureFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(UpstreamFailureFilter.class);
    static final String RETRY_AFTER_SECONDS = "1";

    private final ApiErrorWriter apiErrorWriter;
    private final MeterRegistry registry;

    public UpstreamFailureFilter(ApiErrorWriter apiErrorWriter, MeterRegistry registry) {
        this.apiErrorWriter = apiErrorWriter;
        this.registry = registry;
    }

    static ApiErrorCode classify(Throwable exception) {
        boolean upstreamIo = false;
        for (Throwable cause = exception; cause != null; cause = cause.getCause()) {
            // 로드밸런서가 고를 인스턴스가 없을 때(재배포 중 등) Gateway는 503 상태의 예외를 던진다. 응답이 아니라 500이 된다.
            if (cause instanceof HttpServerErrorException serverError
                && serverError.getStatusCode().value() == HttpStatus.SERVICE_UNAVAILABLE.value()) {
                return ApiErrorCode.UPSTREAM_UNAVAILABLE;
            }
            if (cause instanceof ResourceAccessException) {
                upstreamIo = true;
            }
            if (upstreamIo && cause instanceof HttpConnectTimeoutException) {
                return ApiErrorCode.UPSTREAM_UNAVAILABLE;
            }
            if (upstreamIo && cause instanceof HttpTimeoutException) {
                return ApiErrorCode.UPSTREAM_TIMEOUT;
            }
            if (cause.getCause() == cause) {
                break;
            }
        }
        return upstreamIo ? ApiErrorCode.UPSTREAM_UNAVAILABLE : null;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {
        try {
            filterChain.doFilter(request, response);
        } catch (ServletException | RuntimeException exception) {
            ApiErrorCode code = classify(exception);
            if (code == null || response.isCommitted()) {
                throw exception;
            }
            String route = RouteInFlightLimitFilter.routeOf(request.getRequestURI());
            registry.counter("gateway.upstream.failures", "route", String.valueOf(route), "code", code.name()).increment();
            log.warn("하류 호출 실패 route={} code={} cause={}", route, code, rootMessage(exception));
            response.resetBuffer();
            if (code == ApiErrorCode.UPSTREAM_UNAVAILABLE) {
                response.setHeader(HttpHeaders.RETRY_AFTER, RETRY_AFTER_SECONDS);
            }
            apiErrorWriter.write(request, response, code);
        }
    }

    private static String rootMessage(Throwable exception) {
        Throwable root = exception;
        while (root.getCause() != null && root.getCause() != root) {
            root = root.getCause();
        }
        return root.getClass().getSimpleName();
    }
}
