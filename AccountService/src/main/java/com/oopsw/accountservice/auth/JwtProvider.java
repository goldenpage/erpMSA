package com.oopsw.accountservice.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.oopsw.accountservice.entity.AccountEntity;
import java.time.Duration;
import java.time.Instant;
import com.oopsw.security.RsaJwtVerifier;
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
    private final RsaJwtVerifier verifier;

    public JwtProvider(AuthProperties properties) {
        this.properties = properties;

        verifier = new RsaJwtVerifier(properties.publicKeyDirectory(), properties.issuer(), properties.audience());
        algorithm = verifier.signingAlgorithm(properties.signingKeyId(), properties.privateKeyPath());
    }

    public String createAccessToken(AccountEntity account) {
        Instant now = Instant.now();

        return JWT.create()
            .withKeyId(properties.signingKeyId())
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
            .withKeyId(properties.signingKeyId())
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
        return verifier.verifyAccess(token);
    }

    public DecodedJWT verifyRefreshToken(String token) {
        return verifier.verifyRefresh(token);
    }

    public long getAccessTokenExpiresInSeconds() {
        return properties.accessTtl().toSeconds();
    }

    public Duration getRefreshTtl() {
        return properties.refreshTtl();
    }
}
