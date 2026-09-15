package com.oopsw.accountservice.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.oopsw.security.JwtTestKeys;
import com.oopsw.security.RsaJwtVerifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;

class RsaKeyRotationTest {
    @TempDir Path directory;

    @Test
    void 공개키_선배포_교체_폐기_순서와_조회장애를_검증한다() throws Exception {
        var old = JwtTestKeys.PRIMARY;
        var next = JwtTestKeys.generate("next-k2");
        copy(old);
        var before = verifier();
        String oldToken = token(old.kid(), old.algorithm(), "access", true);
        String oldRefresh = token(old.kid(), old.algorithm(), "refresh", true);
        String nextToken = token(next.kid(), next.algorithm(), "access", true);
        assertThat(before.verifyAccess(oldToken).getKeyId()).isEqualTo(old.kid());
        assertThatThrownBy(() -> before.verifyAccess(nextToken)).isInstanceOf(JWTVerificationException.class);
        copy(next);
        var overlap = verifier();
        assertThat(overlap.verifyAccess(oldToken)).isNotNull();
        assertThat(overlap.verifyAccess(nextToken)).isNotNull();
        assertThat(overlap.verifyRefresh(oldRefresh)).isNotNull();
        Files.delete(directory.resolve(old.kid() + ".pem"));
        var retired = verifier();
        assertThatThrownBy(() -> retired.verifyAccess(oldToken)).isInstanceOf(JWTVerificationException.class);
        assertThat(retired.verifyAccess(nextToken)).isNotNull();
        assertThatThrownBy(() -> retired.verifyRefresh(oldRefresh)).isInstanceOf(JWTVerificationException.class);
        Files.delete(directory.resolve(next.kid() + ".pem"));
        // A running process uses its trusted snapshot; a new empty/missing bundle fails startup.
        assertThat(overlap.verifyAccess(nextToken)).isNotNull();
        assertThatThrownBy(this::verifier).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void kid_경로조작_누락_알고리즘변경_만료없는토큰을_거절한다() throws Exception {
        var keys = JwtTestKeys.PRIMARY;
        copy(keys);
        var verifier = verifier();
        for (String kid : new String[]{"../../private/key", "unknown"}) {
            assertThatThrownBy(() -> verifier.verifyAccess(token(kid, keys.algorithm(), "access", true)))
                .isInstanceOf(JWTVerificationException.class);
        }
        assertThatThrownBy(() -> verifier.verifyAccess(token(null, keys.algorithm(), "access", true)))
            .isInstanceOf(JWTVerificationException.class);
        assertThatThrownBy(() -> verifier.verifyAccess(token(keys.kid(), Algorithm.HMAC256("untrusted"), "access", true)))
            .isInstanceOf(JWTVerificationException.class);
        assertThatThrownBy(() -> verifier.verifyAccess(token(keys.kid(), keys.algorithm(), "access", false)))
            .isInstanceOf(JWTVerificationException.class);
        assertThatThrownBy(() -> verifier.verifyAccess(token(keys.kid(), keys.algorithm(), "refresh", true)))
            .isInstanceOf(JWTVerificationException.class);
    }

    private RsaJwtVerifier verifier() { return new RsaJwtVerifier(directory.toString(), "issuer", "audience"); }
    private void copy(JwtTestKeys.Material keys) throws Exception {
        Files.copy(Path.of(keys.publicDirectory(), keys.kid() + ".pem"), directory.resolve(keys.kid() + ".pem"));
    }
    private String token(String kid, Algorithm algorithm, String type, boolean expires) {
        var token = JWT.create().withIssuer("issuer").withAudience("audience").withSubject("1")
            .withJWTId("test-refresh-id")
            .withIssuedAt(Instant.now()).withClaim("token_type", type)
            .withClaim("email", "test@example.com").withClaim("role", "ROLE_USER");
        if (kid != null) token.withKeyId(kid);
        if (expires) token.withExpiresAt(Instant.now().plusSeconds(60));
        return token.sign(algorithm);
    }
}
