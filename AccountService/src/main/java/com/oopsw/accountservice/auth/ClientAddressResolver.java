package com.oopsw.accountservice.auth;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 시도 제한에 쓸 클라이언트 주소를 정한다.
 *
 * <p>Gateway가 정해서 보낸 {@code X-Client-Address}는 직접 연결한 주소가 {@code trusted-proxies} 대역일 때만 믿는다.
 * 그 밖의 연결(Account에 직접 접속한 경우 등)은 연결 주소를 그대로 쓴다. 운영 환경에서는 Gateway 주소 대역으로 좁혀야 한다.
 */
@Component
public class ClientAddressResolver {

    static final String HEADER = "X-Client-Address";

    private final IpRanges trustedProxies;

    public ClientAddressResolver(
        @Value("${app.auth.rate-limit.trusted-proxies:127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}") String trustedProxies
    ) {
        this.trustedProxies = IpRanges.parse(trustedProxies);
    }

    public String resolve(HttpServletRequest request) {
        String peer = IpRanges.normalize(request.getRemoteAddr());
        if (peer != null && trustedProxies.contains(peer)) {
            String forwarded = IpRanges.normalize(request.getHeader(HEADER));
            if (forwarded != null) {
                return forwarded;
            }
        }
        return peer == null ? "unknown" : peer;
    }
}
