package com.oopsw.gatewayserver;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

@org.junit.jupiter.api.Tag("unit")
class ClientAddressFilterTest {

    private static MockHttpServletRequest request(String remote, String... forwardedFor) {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/account/auth/login");
        request.setRemoteAddr(remote);
        for (String value : forwardedFor) {
            request.addHeader("X-Forwarded-For", value);
        }
        return request;
    }

    private static HttpServletRequest forwarded(ClientAddressFilter filter, MockHttpServletRequest request) throws Exception {
        AtomicReference<HttpServletRequest> seen = new AtomicReference<>();
        filter.doFilter(request, new MockHttpServletResponse(), (req, res) -> seen.set((HttpServletRequest) req));
        return seen.get();
    }

    @Test
    void 신뢰_프록시가_없으면_직접_연결한_주소를_쓰고_클라이언트가_보낸_값은_버린다() throws Exception {
        ClientAddressFilter filter = new ClientAddressFilter("");
        MockHttpServletRequest original = request("203.0.113.7", "198.51.100.1");
        original.addHeader(ClientAddressFilter.HEADER, "10.0.0.1");

        HttpServletRequest forwarded = forwarded(filter, original);

        assertThat(forwarded.getHeader("x-client-address")).isEqualTo("203.0.113.7");
        assertThat(Collections.list(forwarded.getHeaders(ClientAddressFilter.HEADER))).containsExactly("203.0.113.7");
        assertThat(Collections.list(forwarded.getHeaderNames()).stream()
            .filter(name -> name.equalsIgnoreCase(ClientAddressFilter.HEADER))).hasSize(1);
    }

    @Test
    void 신뢰_프록시를_거친_요청은_오른쪽부터_첫_비신뢰_주소를_고른다() {
        ClientAddressFilter filter = new ClientAddressFilter("10.0.0.0/8,172.16.0.0/12");

        // 클라이언트가 맨 왼쪽에 위조 값을 넣어도 신뢰 프록시가 붙인 오른쪽 값이 우선한다.
        assertThat(filter.resolve(request("10.1.2.3", "1.1.1.1, 198.51.100.9, 172.18.0.4"))).isEqualTo("198.51.100.9");
        assertThat(filter.resolve(request("10.1.2.3", "198.51.100.9", "172.18.0.4"))).isEqualTo("198.51.100.9");
        // 직접 연결이 신뢰 프록시가 아니면 X-Forwarded-For는 무시한다.
        assertThat(filter.resolve(request("198.51.100.20", "1.1.1.1"))).isEqualTo("198.51.100.20");
        // 형식이 잘못된 값 왼쪽은 믿지 않는다.
        assertThat(filter.resolve(request("10.1.2.3", "1.1.1.1, evil.example, 172.18.0.4"))).isEqualTo("172.18.0.4");
        // 모든 홉이 신뢰 대역이면 가장 왼쪽 값을 쓴다.
        assertThat(filter.resolve(request("10.1.2.3", "10.9.9.9"))).isEqualTo("10.9.9.9");
        assertThat(filter.resolve(request("10.1.2.3"))).isEqualTo("10.1.2.3");
    }

    @Test
    void CIDR_목록을_검사한다() {
        IpRanges ranges = IpRanges.parse("10.0.0.0/8, 192.168.1.0/24, ::1/128");
        assertThat(ranges.contains("10.255.0.1")).isTrue();
        assertThat(ranges.contains("192.168.2.1")).isFalse();
        assertThat(ranges.contains("::1")).isTrue();
        assertThat(ranges.contains("localhost")).isFalse();
        assertThat(IpRanges.normalize(" 203.0.113.7 ")).isEqualTo("203.0.113.7");
        assertThat(IpRanges.normalize("not-an-ip")).isNull();
        assertThatThrownBy(() -> IpRanges.parse("10.0.0.0/33")).isInstanceOf(IllegalArgumentException.class);
    }
}
