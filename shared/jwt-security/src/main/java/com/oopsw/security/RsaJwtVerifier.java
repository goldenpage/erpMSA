package com.oopsw.security;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.auth0.jwt.interfaces.JWTVerifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;

/** Immutable, trusted public-key snapshot. Rotation is an explicit rolling deployment. */
public final class RsaJwtVerifier {
    private final Map<String, RSAPublicKey> keys;
    private final Map<String, JWTVerifier> access;
    private final Map<String, JWTVerifier> refresh;

    public RsaJwtVerifier(String directory, String issuer, String audience) {
        if (issuer == null || issuer.isBlank() || audience == null || audience.isBlank()) {
            throw new IllegalStateException("JWT issuer와 audience가 필요합니다.");
        }
        Map<String, RSAPublicKey> loaded = new HashMap<>();
        try (var files = Files.list(Path.of(directory))) {
            for (Path file : files.filter(p -> p.getFileName().toString().endsWith(".pem")).toList()) {
                String name = file.getFileName().toString();
                String kid = name.substring(0, name.length() - 4);
                if (!kid.matches("[A-Za-z0-9_-]{1,64}")) {
                    throw new IllegalArgumentException("Invalid key identifier");
                }
                RSAPublicKey key = (RSAPublicKey) KeyFactory.getInstance("RSA").generatePublic(
                    new X509EncodedKeySpec(readPem(file, "PUBLIC KEY")));
                if (key.getModulus().bitLength() < 2048) {
                    throw new IllegalArgumentException("RSA keys require at least 2048 bits");
                }
                loaded.put(kid, key);
            }
            if (loaded.isEmpty()) throw new IllegalArgumentException("Empty public key directory");
        } catch (Exception exception) {
            // Do not include PEM contents or filesystem exception details in application logs.
            throw new IllegalStateException("JWT 공개키 묶음을 읽을 수 없습니다. 경로와 키 형식을 확인하세요.");
        }
        keys = Map.copyOf(loaded);
        access = verifiers(issuer, audience, "access");
        refresh = verifiers(issuer, audience, "refresh");
    }

    private Map<String, JWTVerifier> verifiers(String issuer, String audience, String type) {
        Map<String, JWTVerifier> result = new HashMap<>();
        keys.forEach((kid, key) -> {
            var builder = JWT.require(Algorithm.RSA256(key, null))
                .withIssuer(issuer).withAudience(audience)
                .withClaim("token_type", type).withClaimPresence("sub")
                .withClaimPresence("exp").withClaimPresence("iat").acceptLeeway(30);
            if (type.equals("access")) builder.withClaimPresence("email").withClaimPresence("role");
            else builder.withClaimPresence("jti");
            result.put(kid, builder.build());
        });
        return Map.copyOf(result);
    }

    public DecodedJWT verifyAccess(String token) { return verify(token, access); }
    public DecodedJWT verifyRefresh(String token) { return verify(token, refresh); }

    private DecodedJWT verify(String token, Map<String, JWTVerifier> verifiers) {
        DecodedJWT untrusted = JWT.decode(token);
        String kid = untrusted.getKeyId();
        // kid only selects an already trusted key. It is never used as a file path or URL.
        JWTVerifier verifier = kid == null ? null : verifiers.get(kid);
        if (verifier == null || !"RS256".equals(untrusted.getAlgorithm())) {
            throw new JWTVerificationException("지원하지 않는 JWT 키 또는 알고리즘입니다.");
        }
        return verifier.verify(untrusted);
    }

    /** Only the issuer calls this method; verifier processes never receive the private file. */
    public Algorithm signingAlgorithm(String kid, String privateKeyPath) {
        try {
            RSAPublicKey publicKey = keys.get(kid);
            RSAPrivateKey privateKey = (RSAPrivateKey) KeyFactory.getInstance("RSA").generatePrivate(
                new PKCS8EncodedKeySpec(readPem(Path.of(privateKeyPath), "PRIVATE KEY")));
            if (publicKey == null || !publicKey.getModulus().equals(privateKey.getModulus())) {
                throw new IllegalArgumentException("Signing key does not match public key");
            }
            Algorithm algorithm = Algorithm.RSA256(publicKey, privateKey);
            // Also catch malformed private keys whose modulus happens to match.
            JWT.require(Algorithm.RSA256(publicKey, null)).build().verify(
                JWT.create().withKeyId(kid).sign(algorithm));
            return algorithm;
        } catch (Exception exception) {
            throw new IllegalStateException("JWT 개인키를 읽을 수 없거나 공개키와 일치하지 않습니다.");
        }
    }

    private static byte[] readPem(Path path, String type) throws Exception {
        String pem = Files.readString(path).trim();
        String begin = "-----BEGIN " + type + "-----";
        String end = "-----END " + type + "-----";
        if (!pem.startsWith(begin) || !pem.endsWith(end)) throw new IllegalArgumentException("Invalid PEM");
        return Base64.getDecoder().decode(
            pem.substring(begin.length(), pem.length() - end.length()).replaceAll("\\s", ""));
    }
}
