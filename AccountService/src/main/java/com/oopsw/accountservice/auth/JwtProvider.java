package com.oopsw.accountservice.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.auth0.jwt.interfaces.JWTVerifier;
import com.oopsw.accountservice.entity.AccountEntity;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class JwtProvider {

    public static final String HEADER = "Authorization";
    public static final String PREFIX = "Bearer ";

    private static final String TOKEN_TYPE = "token_type";
    private static final String ACCESS = "access";
    private static final String REFRESH = "refresh";

    private final AuthProperties properties;
    private final Algorithm algorithm;
    private final JWTVerifier accessVerifier;
    private final JWTVerifier refreshVerifier;

    public JwtProvider(AuthProperties properties) {
        this.properties = properties;

        byte[] secret;

        try {
            secret = Base64.getDecoder().decode(properties.secretBase64());
        } catch (IllegalArgumentException exception) {
            throw new IllegalStateException(
                "JWT_SECRET_BASE64가 올바른 Base64 형식이 아닙니다.",
                exception
            );
        }

        if (secret.length < 32) {
            throw new IllegalStateException(
                "HS256 비밀키는 최소 32바이트 이상이어야 합니다."
            );
        }

        this.algorithm = Algorithm.HMAC256(secret);

        this.accessVerifier = JWT.require(algorithm)
            .withIssuer(properties.issuer())
            .withAudience(properties.audience())
            .withClaim(TOKEN_TYPE, ACCESS)
            .withClaimPresence("sub")
            .withClaimPresence("email")
            .withClaimPresence("role")
            .acceptLeeway(30)
            .build();

        this.refreshVerifier = JWT.require(algorithm)
            .withIssuer(properties.issuer())
            .withAudience(properties.audience())
            .withClaim(TOKEN_TYPE, REFRESH)
            .withClaimPresence("sub")
            .withClaimPresence("jti")
            .acceptLeeway(30)
            .build();
    }

    public String createAccessToken(AccountEntity account) {
        Instant now = Instant.now();

        return JWT.create()
            .withIssuer(properties.issuer())
            .withAudience(properties.audience())
            .withSubject(account.getId().toString())
            .withIssuedAt(now)
            .withExpiresAt(now.plus(properties.accessTtl()))
            .withClaim(TOKEN_TYPE, ACCESS)
            .withClaim("email", account.getEmail())
            .withClaim("businessId", account.getBusinessId())
            .withClaim("role", account.getRole().name())
            .sign(algorithm);
    }

    public String createRefreshToken(AccountEntity account) {
        Instant now = Instant.now();

        return JWT.create()
            .withIssuer(properties.issuer())
            .withAudience(properties.audience())
            .withSubject(account.getId().toString())
            .withJWTId(UUID.randomUUID().toString())
            .withIssuedAt(now)
            .withExpiresAt(now.plus(properties.refreshTtl()))
            .withClaim(TOKEN_TYPE, REFRESH)
            .sign(algorithm);
    }

    public DecodedJWT verifyAccessToken(String token) {
        return accessVerifier.verify(token);
    }

    public DecodedJWT verifyRefreshToken(String token) {
        return refreshVerifier.verify(token);
    }

    public long getAccessTokenExpiresInSeconds() {
        return properties.accessTtl().toSeconds();
    }

    public Duration getRefreshTtl() {
        return properties.refreshTtl();
    }
}
