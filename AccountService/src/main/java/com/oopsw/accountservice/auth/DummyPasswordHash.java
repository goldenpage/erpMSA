package com.oopsw.accountservice.auth;

import java.util.UUID;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

/**
 * 없는 이메일로 로그인할 때 비교할 해시. 실제 계정과 같은 인코더·비용으로 만든다.
 * 없는 이메일도 같은 BCrypt 비용을 쓰게 해 응답시간으로 가입 여부를 알 수 없게 한다.
 * 원문은 저장하지 않으므로 어떤 비밀번호와도 일치하지 않는다.
 */
@Component
public class DummyPasswordHash {

    private final String value;

    public DummyPasswordHash(PasswordEncoder passwordEncoder) {
        // BCrypt 입력 한도(72바이트) 안의 임의 값. UUID 하나는 36바이트다.
        this.value = passwordEncoder.encode(UUID.randomUUID().toString());
    }

    public String value() {
        return value;
    }
}
