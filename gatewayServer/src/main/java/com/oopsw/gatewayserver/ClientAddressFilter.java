package com.oopsw.gatewayserver;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 하류 서비스로 보내는 {@value #HEADER} 헤더를 Gateway가 직접 정한다.
 *
 * <p>클라이언트가 보낸 같은 이름의 헤더는 항상 버린다. 기본값은 Gateway에 직접 연결한 주소다.
 * Gateway 앞에 로드밸런서처럼 믿을 수 있는 프록시가 있으면 {@code trusted-upstreams}에 그 주소 대역을 지정한다.
 * 이때만 {@code X-Forwarded-For}를 오른쪽부터 읽어 믿을 수 있는 프록시가 아닌 첫 주소를 클라이언트로 본다.
 * 하류 서비스(Account 로그인 시도 제한 등)는 이 헤더만 사용한다.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ClientAddressFilter extends OncePerRequestFilter {

    static final String HEADER = "X-Client-Address";

    private final IpRanges trustedUpstreams;

    public ClientAddressFilter(@Value("${app.gateway.client-address.trusted-upstreams:}") String trustedUpstreams) {
        this.trustedUpstreams = IpRanges.parse(trustedUpstreams);
    }

    String resolve(HttpServletRequest request) {
        String peer = IpRanges.normalize(request.getRemoteAddr());
        if (peer == null) {
            return null;
        }
        if (trustedUpstreams.isEmpty() || !trustedUpstreams.contains(peer)) {
            return peer;
        }
        List<String> hops = new ArrayList<>();
        for (Enumeration<String> values = request.getHeaders("X-Forwarded-For"); values != null && values.hasMoreElements(); ) {
            for (String hop : values.nextElement().split(",")) {
                hops.add(hop.trim());
            }
        }
        String candidate = peer;
        for (int i = hops.size() - 1; i >= 0; i--) {
            String hop = IpRanges.normalize(hops.get(i));
            if (hop == null) {
                // 형식이 잘못된 값이 끼어 있으면 그 왼쪽은 믿지 않는다.
                return candidate;
            }
            candidate = hop;
            if (!trustedUpstreams.contains(hop)) {
                return hop;
            }
        }
        return candidate;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {
        filterChain.doFilter(new ClientAddressRequest(request, resolve(request)), response);
    }

    /** 클라이언트가 보낸 {@value #HEADER}를 가리고 Gateway가 정한 값만 보이게 한다. */
    static final class ClientAddressRequest extends HttpServletRequestWrapper {

        private final String clientAddress;

        ClientAddressRequest(HttpServletRequest request, String clientAddress) {
            super(request);
            this.clientAddress = clientAddress;
        }

        private static boolean isClientHeader(String name) {
            return HEADER.equalsIgnoreCase(name);
        }

        @Override
        public String getHeader(String name) {
            return isClientHeader(name) ? clientAddress : super.getHeader(name);
        }

        @Override
        public Enumeration<String> getHeaders(String name) {
            if (isClientHeader(name)) {
                return clientAddress == null ? Collections.emptyEnumeration()
                    : Collections.enumeration(List.of(clientAddress));
            }
            return super.getHeaders(name);
        }

        @Override
        public Enumeration<String> getHeaderNames() {
            List<String> names = new ArrayList<>();
            for (Enumeration<String> e = super.getHeaderNames(); e.hasMoreElements(); ) {
                String name = e.nextElement();
                if (!isClientHeader(name)) {
                    names.add(name);
                }
            }
            if (clientAddress != null) {
                names.add(HEADER);
            }
            return Collections.enumeration(names);
        }
    }
}
