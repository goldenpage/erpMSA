FROM eclipse-temurin:21-jdk-jammy AS builder

WORKDIR /workspace/DisposalsService

COPY DisposalsService/gradlew DisposalsService/build.gradle DisposalsService/settings.gradle ./
COPY shared/jwt-security/build.gradle /workspace/shared/jwt-security/build.gradle
COPY shared/service-foundation/build.gradle /workspace/shared/service-foundation/build.gradle
COPY DisposalsService/gradle ./gradle
RUN chmod +x gradlew
RUN ./gradlew dependencies --no-daemon

COPY DisposalsService/src ./src
COPY shared/jwt-security/src/main /workspace/shared/jwt-security/src/main
COPY shared/service-foundation/src/main /workspace/shared/service-foundation/src/main
RUN ./gradlew bootJar --no-daemon -x test \
    && cp "$(find build/libs -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)" app.jar

FROM eclipse-temurin:21-jre-jammy

WORKDIR /app
RUN groupadd --system spring \
    && useradd --system --gid spring spring

COPY --from=builder --chown=spring:spring /workspace/DisposalsService/app.jar ./app.jar

USER spring:spring
EXPOSE 7077

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
