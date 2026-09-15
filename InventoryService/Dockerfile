FROM eclipse-temurin:21-jdk-jammy AS builder

WORKDIR /workspace/InventoryService

COPY InventoryService/gradlew InventoryService/build.gradle InventoryService/settings.gradle ./
COPY shared/jwt-security/build.gradle /workspace/shared/jwt-security/build.gradle
COPY InventoryService/gradle ./gradle
RUN chmod +x gradlew
RUN ./gradlew dependencies --no-daemon

COPY InventoryService/src ./src
COPY shared/jwt-security/src/main /workspace/shared/jwt-security/src/main
RUN ./gradlew bootJar --no-daemon -x test \
    && cp "$(find build/libs -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)" app.jar

FROM eclipse-temurin:21-jre-jammy

WORKDIR /app
RUN groupadd --system spring \
    && useradd --system --gid spring spring

COPY --from=builder --chown=spring:spring /workspace/InventoryService/app.jar ./app.jar

USER spring:spring
EXPOSE 7074

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
