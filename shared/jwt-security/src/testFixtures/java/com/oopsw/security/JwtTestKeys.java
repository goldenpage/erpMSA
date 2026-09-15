package com.oopsw.security;

import com.auth0.jwt.algorithms.Algorithm;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.util.Base64;

/** Ephemeral test keys; never packaged in service boot jars. */
public final class JwtTestKeys {
    public static final Material PRIMARY = generate("test-k1");
    public static final Material OTHER = generate("test-k1");
    private JwtTestKeys() {}
    public static Material generate(String kid) {
        try {
            var generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(2048);
            var pair = generator.generateKeyPair();
            Path directory = Files.createTempDirectory("erpmsa-jwt-test-");
            Path publicDirectory = Files.createDirectory(directory.resolve("public"));
            Path privateFile = directory.resolve("private.key");
            Files.writeString(publicDirectory.resolve(kid + ".pem"), pem("PUBLIC KEY", pair.getPublic().getEncoded()));
            Files.writeString(privateFile, pem("PRIVATE KEY", pair.getPrivate().getEncoded()));
            Files.setPosixFilePermissions(privateFile, java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
            publicDirectory.resolve(kid + ".pem").toFile().deleteOnExit();
            privateFile.toFile().deleteOnExit();
            return new Material(kid, publicDirectory.toString(), privateFile.toString(),
                Algorithm.RSA256((RSAPublicKey) pair.getPublic(), (RSAPrivateKey) pair.getPrivate()));
        } catch (Exception exception) { throw new IllegalStateException(exception); }
    }
    private static String pem(String type, byte[] bytes) {
        return "-----BEGIN " + type + "-----\n" + Base64.getMimeEncoder(64, new byte[]{10}).encodeToString(bytes)
            + "\n-----END " + type + "-----\n";
    }
    public record Material(String kid, String publicDirectory, String privatePath, Algorithm algorithm) {}
}
