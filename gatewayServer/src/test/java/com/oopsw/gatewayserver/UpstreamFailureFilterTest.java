package com.oopsw.gatewayserver;

import static org.assertj.core.api.Assertions.assertThat;

import com.oopsw.gatewayserver.api.ApiErrorCode;
import java.io.IOException;
import java.net.ConnectException;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpTimeoutException;
import java.nio.channels.UnresolvedAddressException;
import jakarta.servlet.ServletException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;

@org.junit.jupiter.api.Tag("unit")
class UpstreamFailureFilterTest {

    private static ServletException wrapped(Throwable cause) {
        return new ServletException("Request processing failed",
            new ResourceAccessException("I/O error on GET request", cause instanceof IOException io ? io : new IOException(cause)));
    }

    @Test
    void 연결_단계_실패는_503으로_분류한다() {
        assertThat(UpstreamFailureFilter.classify(wrapped(new ConnectException("refused")))).isEqualTo(ApiErrorCode.UPSTREAM_UNAVAILABLE);
        assertThat(UpstreamFailureFilter.classify(wrapped(new UnresolvedAddressException()))).isEqualTo(ApiErrorCode.UPSTREAM_UNAVAILABLE);
        assertThat(UpstreamFailureFilter.classify(wrapped(new HttpConnectTimeoutException("connect timed out"))))
            .isEqualTo(ApiErrorCode.UPSTREAM_UNAVAILABLE);
    }

    @Test
    void 로드밸런서가_고를_인스턴스가_없으면_503으로_분류한다() {
        HttpServerErrorException noInstance = HttpServerErrorException.create(HttpStatus.SERVICE_UNAVAILABLE,
            "Unable to find instance for ACCOUNTSERVICE", HttpHeaders.EMPTY, null, null);
        assertThat(UpstreamFailureFilter.classify(new ServletException("Request processing failed", noInstance)))
            .isEqualTo(ApiErrorCode.UPSTREAM_UNAVAILABLE);
        HttpServerErrorException other = HttpServerErrorException.create(HttpStatus.INTERNAL_SERVER_ERROR,
            "boom", HttpHeaders.EMPTY, null, null);
        assertThat(UpstreamFailureFilter.classify(new ServletException(other))).isNull();
    }

    @Test
    void 응답_읽기_시간_초과는_504로_분류한다() {
        assertThat(UpstreamFailureFilter.classify(wrapped(new HttpTimeoutException("request timed out"))))
            .isEqualTo(ApiErrorCode.UPSTREAM_TIMEOUT);
    }

    @Test
    void 하류_호출과_무관한_예외는_건드리지_않는다() {
        assertThat(UpstreamFailureFilter.classify(new ServletException(new IllegalStateException("bug")))).isNull();
        assertThat(UpstreamFailureFilter.classify(new IllegalArgumentException("bug"))).isNull();
    }
}
