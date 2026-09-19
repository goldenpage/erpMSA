pipeline {
    agent any

    options {
        timestamps()
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        buildDiscarder(logRotator(
            numToKeepStr: '20',
            artifactNumToKeepStr: '10'
        ))
        timeout(time: 30, unit: 'MINUTES')
    }

    triggers {
        pollSCM('H/2 * * * *')
    }

    environment {
        CI_PROJECT_NAME = "erpmsa-ci-${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                // Removed/renamed modules can leave untracked Gradle output behind.
                deleteDir()
                checkout scm
            }
        }

        stage('Prepare') {
            steps {
                withCredentials([
                    string(
                        credentialsId: 'erpmsa-ci-db-password',
                        variable: 'ERPMSA_DB_PASSWORD'
                    )
                ]) {
                    sh '''
                        set +x
                        umask 077

                        ./scripts/generate-jwt-keys.sh "ci-$BUILD_NUMBER" secrets/jwt-ci

                        # Docker daemon runs outside Jenkins: transfer keys to named volumes.
                        tar -C secrets/jwt-ci/public -cf - . | docker run --rm -i \
                            -v "${CI_PROJECT_NAME}-jwt-public:/keys" mariadb:10.11 \
                            sh -ec 'tar -xf - -C /keys; chmod 755 /keys; chmod 444 /keys/*.pem'
                        tar -C secrets/jwt-ci/private -cf - "ci-$BUILD_NUMBER.pem" | docker run --rm -i \
                            -v "${CI_PROJECT_NAME}-jwt-private:/keys" mariadb:10.11 \
                            sh -ec 'tar -xf - -C /keys; chmod 755 /keys; chmod 444 /keys/*.pem'

                        GRAFANA_CI_ADMIN_PASSWORD=$(openssl rand -hex 32)
                        GRAFANA_CI_SECRET_KEY=$(openssl rand -hex 32)

                        {
                            printf 'DB_PASSWORD=%s\\n' "$ERPMSA_DB_PASSWORD"
                            printf 'JWT_SIGNING_KEY_ID=ci-%s\\n' "$BUILD_NUMBER"
                            printf 'JWT_PUBLIC_KEYS_HOST_DIR=./secrets/jwt-ci/public\\n'
                            printf 'JWT_PRIVATE_KEY_HOST_FILE=./secrets/jwt-ci/private/ci-%s.pem\\n' "$BUILD_NUMBER"
                            printf 'JWT_ISSUER=kosta-erp-account\\n'
                            printf 'JWT_AUDIENCE=kosta-erp-api\\n'
                            printf 'PROMETHEUS_RETENTION_TIME=1d\\n'
                            printf 'GRAFANA_ADMIN_USER=admin\\n'
                            printf 'GRAFANA_ADMIN_PASSWORD=%s\\n' \
                                "$GRAFANA_CI_ADMIN_PASSWORD"
                            printf 'GRAFANA_SECRET_KEY=%s\\n' \
                                "$GRAFANA_CI_SECRET_KEY"
                            printf 'GRAFANA_COOKIE_SECURE=false\\n'
                            printf 'CI_PROJECT_NAME=%s\\n' "$CI_PROJECT_NAME"
                            printf 'BUILD_NUMBER=%s\\n' "$BUILD_NUMBER"
                        } > .env
                    '''
                }
            }
        }

        stage('Validate Compose') {
            steps {
                sh '''
                    docker compose \
                        -f compose.yaml \
                        -f compose.ci.yaml \
                        -p "$CI_PROJECT_NAME" \
                        config --quiet
                    python3 scripts/verify-service-architecture.py --ci
                '''
            }
        }

        stage('Start Test Infrastructure') {
            steps {
                sh '''
                    docker compose \
                        -f compose.yaml \
                        -f compose.ci.yaml \
                        -p "$CI_PROJECT_NAME" \
                        up -d --wait \
                        mariadb redis kafka eureka-server

                    docker network connect \
                        "${CI_PROJECT_NAME}_default" \
                        erpmsa-jenkins || true
                '''
            }
        }

        stage('Gradle Test') {
            // Keep one Gradle build active when CI shares Docker Desktop with ERP.
            stages {
                stage('Eureka Test') {
                    steps {
                        sh '''
                            ./eurekaServer/gradlew \
                                -p eurekaServer \
                                test --no-daemon
                        '''
                    }
                }

                stage('Gateway Test') {
                    steps {
                        sh '''
                            set +x
                            set -a
                            . ./.env
                            set +a

                            EUREKA_DEFAULT_ZONE=http://eureka-server:8761/eureka \
                            ./gatewayServer/gradlew \
                                -p gatewayServer \
                                test --no-daemon
                        '''
                    }
                }

                stage('Account Test') {
                    steps {
                        sh '''
                            COOKIE_SECURE=false \
                            ./AccountService/gradlew \
                                -p AccountService \
                                test --no-daemon
                        '''
                    }
                }

                stage('FoodMaterials Test') {
                    steps {
                        sh '''
                            ./FoodMaterialsService/gradlew \
                                -p FoodMaterialsService \
                                test --no-daemon
                        '''
                    }
                }

                stage('Designed Services Test') {
                    steps {
                        sh '''
                            for SERVICE in MenusService NoticesService BillsService PurchaseService DisposalsService; do
                                ./$SERVICE/gradlew -p "$SERVICE" test --no-daemon
                            done
                        '''
                    }
                }

            }
        }

        stage('Build Images') {
            steps {
                sh '''
                    set -eu
                    for SERVICE in eureka-server account-service foodmaterials-service \
                        menus-service notices-service bills-service purchase-service \
                        disposals-service gateway-server prometheus grafana; do
                        docker compose \
                            -f compose.yaml \
                            -f compose.ci.yaml \
                            -p "$CI_PROJECT_NAME" \
                            build "$SERVICE"
                    done
                '''
            }
        }

        stage('Start Application') {
            steps {
                sh '''
                    docker compose \
                        -f compose.yaml \
                        -f compose.ci.yaml \
                        -p "$CI_PROJECT_NAME" \
                        up -d --wait
                '''
            }
        }

        stage('Monitoring Smoke Test') {
            steps {
                sh '''
                    set +x
                    set -eu
                    set -a
                    . ./.env
                    set +a

                    PROMETHEUS_FILE=/tmp/erpmsa-ci-prometheus.json
                    TARGET_COUNT=0

                    PROMETHEUS_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        http://prometheus:9090/-/ready)

                    GRAFANA_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        http://grafana:3000/api/health)

                    for ATTEMPT in $(seq 1 30); do
                        if curl \
                            -sS \
                            --fail \
                            --connect-timeout 2 \
                            --max-time 10 \
                            --get \
                            --data-urlencode \
                            'query=up{job=~"eureka-server|account-service|foodmaterials-service|menus-service|notices-service|bills-service|purchase-service|disposals-service|gateway-server"}' \
                            -o "$PROMETHEUS_FILE" \
                            http://prometheus:9090/api/v1/query; then

                            TARGET_COUNT=$(jq \
                                '[.data.result[] | select(.value[1] == "1")] | length' \
                                "$PROMETHEUS_FILE")
                        fi

                        printf \
                        'Prometheus target check: attempt=%s up=%s/9\n' \
                            "$ATTEMPT" \
                            "$TARGET_COUNT"

                        if [ "$TARGET_COUNT" -eq 9 ]; then
                            break
                        fi

                        sleep 2
                    done

                    DASHBOARD_COUNT=$(curl \
                        -sS \
                        --fail \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" \
                        'http://grafana:3000/api/search?query=ErpMSA%20Spring%20Services' \
                        | jq \
                            '[.[] | select(.uid == "erpmsa-spring-services")] | length')

                    printf \
                        'prometheus=%s grafana=%s targets=%s dashboard=%s\n' \
                        "$PROMETHEUS_STATUS" \
                        "$GRAFANA_STATUS" \
                        "$TARGET_COUNT" \
                        "$DASHBOARD_COUNT"

                    test "$PROMETHEUS_STATUS" = "200"
                    test "$GRAFANA_STATUS" = "200"
                    test "$TARGET_COUNT" -eq 9
                    test "$DASHBOARD_COUNT" -eq 1

                    rm -f "$PROMETHEUS_FILE"
                '''
            }
        }

        stage('Authentication Smoke Test') {
            steps {
                sh '''
                    set +x
                    set -eu

                    COOKIE_FILE=/tmp/erpmsa-ci-cookie.txt
                    LOGIN_FILE=/tmp/erpmsa-ci-login.json
                    FOOD_MATERIAL_FILE=/tmp/erpmsa-ci-foodmaterial.json
                    BUSINESS_ID=$(printf '%010d' "$BUILD_NUMBER")
                    TEST_EMAIL="jenkins-${BUILD_NUMBER}@example.com"

                    # Gateway가 AccountService를 Eureka에서 조회할 때까지 대기한다.
                    # AccountService까지 요청이 전달되면 GET /login은 405가 된다.
                    # Eureka에 아직 등록되지 않았다면 Gateway가 503을 반환한다.
                    ROUTE_STATUS=000

                    for ATTEMPT in $(seq 1 30); do
                        ROUTE_STATUS=$(curl \
                            -sS \
                            --connect-timeout 2 \
                            --max-time 5 \
                            -o /dev/null \
                            -w '%{http_code}' \
                            http://gateway-server:7070/account/auth/login \
                            || true)

                        printf \
                            'Gateway route check: attempt=%s status=%s\\n' \
                            "$ATTEMPT" \
                            "$ROUTE_STATUS"

                        if [ "$ROUTE_STATUS" = "405" ]; then
                            echo 'Gateway에서 AccountService 라우팅이 준비되었습니다.'
                            break
                        fi

                        sleep 2
                    done

                    if [ "$ROUTE_STATUS" != "405" ]; then
                        printf \
                            'Gateway 라우팅 준비 실패: 마지막 HTTP 상태=%s\\n' \
                            "$ROUTE_STATUS"
                        exit 1
                    fi

                    NO_TOKEN_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        http://gateway-server:7070/account/auth/me)

                    REGISTER_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -H 'Content-Type: application/json' \
                        -d "{
                            \\"email\\": \\"${TEST_EMAIL}\\",
                            \\"businessId\\": \\"${BUSINESS_ID}\\",
                            \\"password\\": \\"Test1234!\\",
                            \\"name\\": \\"Jenkins Test\\",
                            \\"phone\\": \\"01012345678\\",
                            \\"storeName\\": \\"Jenkins Store\\",
                            \\"storeType\\": \\"RETAIL\\",
                            \\"storeCategory\\": \\"TEST\\",
                            \\"marketingAgreed\\": false
                        }" \
                        http://gateway-server:7070/account/auth/register)

                    LOGIN_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -c "$COOKIE_FILE" \
                        -o "$LOGIN_FILE" \
                        -w '%{http_code}' \
                        -H 'Content-Type: application/json' \
                        -d "{
                            \\"email\\": \\"${TEST_EMAIL}\\",
                            \\"password\\": \\"Test1234!\\"
                        }" \
                        http://gateway-server:7070/account/auth/login)

                    printf \
                        'route=%s no_token=%s register=%s login=%s\\n' \
                        "$ROUTE_STATUS" \
                        "$NO_TOKEN_STATUS" \
                        "$REGISTER_STATUS" \
                        "$LOGIN_STATUS"

                    test "$NO_TOKEN_STATUS" = "401"
                    test "$REGISTER_STATUS" = "201"
                    test "$LOGIN_STATUS" = "200"

                    ACCESS_TOKEN=$(jq -r \
                        '.accessToken // empty' \
                        "$LOGIN_FILE")

                    if [ -z "$ACCESS_TOKEN" ]; then
                        echo 'Access Token이 발급되지 않았습니다.'
                        exit 1
                    fi

                    # Verify discovery and honest 501 contracts for the three pending domain shells.
                    for SERVICE_PATH in notices bills purchase; do
                        SHELL_STATUS=000
                        for ATTEMPT in $(seq 1 45); do
                            SHELL_STATUS=$(curl -sS --connect-timeout 2 --max-time 5 \
                                -o /tmp/erpmsa-ci-service-contract.json -w '%{http_code}' \
                                -H "Authorization: Bearer $ACCESS_TOKEN" \
                                "http://gateway-server:7070/$SERVICE_PATH" || true)
                            if [ "$SHELL_STATUS" = "501" ]; then break; fi
                            sleep 2
                        done
                        test "$SHELL_STATUS" = "501"
                        test "$(jq -r '.code' /tmp/erpmsa-ci-service-contract.json)" = "ENDPOINT_NOT_IMPLEMENTED"
                    done
                    rm -f /tmp/erpmsa-ci-service-contract.json

                    FOOD_MATERIAL_ROUTE_STATUS=000

                    for ATTEMPT in $(seq 1 30); do
                        FOOD_MATERIAL_ROUTE_STATUS=$(curl \
                            -sS \
                            --connect-timeout 2 \
                            --max-time 5 \
                            -o /dev/null \
                            -w '%{http_code}' \
                            -H "Authorization: Bearer $ACCESS_TOKEN" \
                            http://gateway-server:7070/foodmaterials \
                            || true)

                        printf \
                            'FoodMaterials route check: attempt=%s status=%s\\n' \
                            "$ATTEMPT" \
                            "$FOOD_MATERIAL_ROUTE_STATUS"

                        if [ "$FOOD_MATERIAL_ROUTE_STATUS" = "200" ]; then
                            break
                        fi

                        sleep 2
                    done

                    test "$FOOD_MATERIAL_ROUTE_STATUS" = "200"

                    FOOD_MATERIAL_BODY=$(jq -nc \
                        --arg sku "JENKINS-$BUILD_NUMBER" \
                        '{
                            sku: $sku,
                            name: "Jenkins FoodMaterial",
                            description: "CI smoke test",
                            unitPrice: 1000.00
                        }')

                    FOOD_MATERIAL_CREATE_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o "$FOOD_MATERIAL_FILE" \
                        -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" \
                        -H 'Content-Type: application/json' \
                        --data "$FOOD_MATERIAL_BODY" \
                        http://gateway-server:7070/foodmaterials)

                    FOOD_MATERIAL_ID=$(jq -r '.foodMaterialId // empty' "$FOOD_MATERIAL_FILE")
                    printf 'FoodMaterial create status=%s\\n' "$FOOD_MATERIAL_CREATE_STATUS"

                    if [ -z "$FOOD_MATERIAL_ID" ]; then
                        echo 'FoodMaterial ID가 반환되지 않았습니다.'
                        exit 1
                    fi

                    FOOD_MATERIAL_GET_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" \
                        "http://gateway-server:7070/foodmaterials/$FOOD_MATERIAL_ID")

                    INVENTORY_FILE=/tmp/erpmsa-ci-foodmaterial-inventory.json
                    STOCK_BODY=$(jq -nc --argjson id "$FOOD_MATERIAL_ID" '{foodMaterialId:$id,initialQuantity:20}')
                    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
                        -o "$INVENTORY_FILE" -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
                        --data "$STOCK_BODY" http://gateway-server:7070/foodmaterials/inventories)
                    printf 'Inventory create status=%s\\n' "$STOCK_STATUS"
                    test "$STOCK_STATUS" = "201"
                    STOCK_VERSION=$(jq -er '.version' "$INVENTORY_FILE")
                    STOCK_BODY=$(jq -nc --argjson version "$STOCK_VERSION" --arg id "CI-STOCK-$BUILD_NUMBER" \
                        '{requestId:$id,quantityDelta:-3,reason:"CI smoke",version:$version}')
                    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
                        -o "$INVENTORY_FILE" -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
                        --data "$STOCK_BODY" "http://gateway-server:7070/foodmaterials/inventories/$FOOD_MATERIAL_ID/adjustments")
                    printf 'Inventory adjustment status=%s\\n' "$STOCK_STATUS"
                    test "$STOCK_STATUS" = "200"
                    test "$(jq -er '.inventory.onHandQuantity' "$INVENTORY_FILE")" = "17"
                    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
                        -o "$INVENTORY_FILE" -w '%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" \
                        "http://gateway-server:7070/foodmaterials/inventories/$FOOD_MATERIAL_ID/movements")
                    printf 'Inventory movements status=%s\\n' "$STOCK_STATUS"
                    test "$STOCK_STATUS" = "200"
                    test "$(jq -er '.totalElements' "$INVENTORY_FILE")" = "2"
                    rm -f "$INVENTORY_FILE"

                    BUSINESS_FILE=/tmp/erpmsa-ci-business.json
                    # Health checks can pass before Gateway refreshes its Eureka registry.
                    for SERVICE_PATH in menus disposals; do
                        BUSINESS_ROUTE_STATUS=000
                        for ATTEMPT in $(seq 1 45); do
                            BUSINESS_ROUTE_STATUS=$(curl -sS --connect-timeout 2 --max-time 5 \
                                -o /dev/null -w '%{http_code}' \
                                -H "Authorization: Bearer $ACCESS_TOKEN" \
                                "http://gateway-server:7070/$SERVICE_PATH" || true)
                            printf 'Business route check: service=%s attempt=%s status=%s\\n' \
                                "$SERVICE_PATH" "$ATTEMPT" "$BUSINESS_ROUTE_STATUS"
                            if [ "$BUSINESS_ROUTE_STATUS" = "200" ]; then break; fi
                            sleep 2
                        done
                        test "$BUSINESS_ROUTE_STATUS" = "200"
                    done

                    MENU_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o "$BUSINESS_FILE" -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
                        --data '{"name":"CI menu","price":12000}' http://gateway-server:7070/menus)
                    printf 'Menu create status=%s\\n' "$MENU_STATUS"
                    test "$MENU_STATUS" = "201"
                    MENU_ID=$(jq -er '.menuId' "$BUSINESS_FILE")
                    MENU_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" -X DELETE "http://gateway-server:7070/menus/$MENU_ID")
                    printf 'Menu delete status=%s\\n' "$MENU_STATUS"
                    test "$MENU_STATUS" = "204"
                    DISPOSAL_BODY=$(jq -nc --arg id "CI-DISPOSAL-$BUILD_NUMBER" --argjson material "$FOOD_MATERIAL_ID" \
                        '{requestId:$id,foodMaterialId:$material,quantity:2,reason:"CI disposal"}')
                    for REPLAY in 1 2; do
                        DISPOSAL_STATUS=$(curl -sS --connect-timeout 2 --max-time 15 -o "$BUSINESS_FILE" -w '%{http_code}' \
                            -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
                            --data "$DISPOSAL_BODY" http://gateway-server:7070/disposals)
                        printf 'Disposal replay=%s http=%s state=%s\\n' "$REPLAY" "$DISPOSAL_STATUS" "$(jq -r '.status // .code // "unknown"' "$BUSINESS_FILE")"
                        test "$DISPOSAL_STATUS" = "200"
                        test "$(jq -r '.status' "$BUSINESS_FILE")" = "COMPLETED"
                        test "$(jq -r '.quantityAfter' "$BUSINESS_FILE")" = "15"
                    done
                    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o "$BUSINESS_FILE" -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" "http://gateway-server:7070/foodmaterials/inventories/$FOOD_MATERIAL_ID")
                    test "$STOCK_STATUS" = "200"
                    test "$(jq -r '.onHandQuantity' "$BUSINESS_FILE")" = "15"
                    rm -f "$BUSINESS_FILE"

                    for LEGACY_PATH in items inventories orders; do
                        LEGACY_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
                            -o /dev/null -w '%{http_code}' \
                            -H "Authorization: Bearer $ACCESS_TOKEN" \
                            "http://gateway-server:7070/$LEGACY_PATH")
                        test "$LEGACY_STATUS" = "404"
                    done

                    ME_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" \
                        http://gateway-server:7070/account/auth/me)

                    REFRESH_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -b "$COOKIE_FILE" \
                        -c "$COOKIE_FILE" \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -X POST \
                        http://gateway-server:7070/account/auth/refresh)

                    LOGOUT_STATUS=$(curl \
                        -sS \
                        --connect-timeout 2 \
                        --max-time 10 \
                        -b "$COOKIE_FILE" \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -X POST \
                        http://gateway-server:7070/account/auth/logout)

                    AFTER_LOGOUT_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
                        -b "$COOKIE_FILE" -o /dev/null -w '%{http_code}' -X POST \
                        http://gateway-server:7070/account/auth/refresh)
                    test "$AFTER_LOGOUT_STATUS" = "401"

                    printf \
                        'foodmaterials_route=%s foodmaterials_create=%s foodmaterials_get=%s me=%s refresh=%s logout=%s\\n' \
                        "$FOOD_MATERIAL_ROUTE_STATUS" \
                        "$FOOD_MATERIAL_CREATE_STATUS" \
                        "$FOOD_MATERIAL_GET_STATUS" \
                        "$ME_STATUS" \
                        "$REFRESH_STATUS" \
                        "$LOGOUT_STATUS"

                    test "$FOOD_MATERIAL_CREATE_STATUS" = "201"
                    test "$FOOD_MATERIAL_GET_STATUS" = "200"
                    test "$ME_STATUS" = "200"
                    test "$REFRESH_STATUS" = "200"
                    test "$LOGOUT_STATUS" = "204"

                    rm -f \
                        "$COOKIE_FILE" \
                        "$LOGIN_FILE" \
                        "$FOOD_MATERIAL_FILE"
                '''
            }
        }

        stage('Kafka Publish Smoke Test') {
            steps {
                sh '''
                    set +x
                    set -eu

                    PUBLISHED_COUNT=0
                    PENDING_COUNT=1

                    for ATTEMPT in $(seq 1 30); do
                        PUBLISHED_COUNT=$(docker compose \
                            -f compose.yaml \
                            -f compose.ci.yaml \
                            -p "$CI_PROJECT_NAME" \
                            exec -T mariadb sh -ec \
                            'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb \
                            --host=127.0.0.1 --user=root \
                            --batch --skip-column-names \
                            --execute="SELECT COUNT(*) FROM mydb.account_outbox_event WHERE status = '\\''PUBLISHED'\\'';"')

                        PENDING_COUNT=$(docker compose \
                            -f compose.yaml \
                            -f compose.ci.yaml \
                            -p "$CI_PROJECT_NAME" \
                            exec -T mariadb sh -ec \
                            'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb \
                            --host=127.0.0.1 --user=root \
                            --batch --skip-column-names \
                            --execute="SELECT COUNT(*) FROM mydb.account_outbox_event WHERE status != '\\''PUBLISHED'\\'';"')

                        printf \
                            'Kafka event check: attempt=%s published=%s pending=%s\n' \
                            "$ATTEMPT" \
                            "$PUBLISHED_COUNT" \
                            "$PENDING_COUNT"

                        if [ "$PUBLISHED_COUNT" -eq 1 ] && \
                            [ "$PENDING_COUNT" -eq 0 ]; then
                            break
                        fi

                        sleep 2
                    done

                    test "$PUBLISHED_COUNT" -eq 1
                    test "$PENDING_COUNT" -eq 0
                '''
            }
        }
    }

    post {
        always {
            junit(
                testResults: '**/build/test-results/test/*.xml',
                allowEmptyResults: true
            )

            sh '''
                docker compose \
                    -f compose.yaml \
                    -f compose.ci.yaml \
                    -p "$CI_PROJECT_NAME" \
                    ps > compose-ps.txt 2>&1 || true

                docker compose \
                    -f compose.yaml \
                    -f compose.ci.yaml \
                    -p "$CI_PROJECT_NAME" \
                    logs --no-color > compose.log 2>&1 || true
            '''

            archiveArtifacts(
                artifacts: 'compose-ps.txt,compose.log',
                allowEmptyArchive: true
            )

            sh '''
                docker network disconnect \
                    "${CI_PROJECT_NAME}_default" \
                    erpmsa-jenkins || true

                docker compose \
                    -f compose.yaml \
                    -f compose.ci.yaml \
                    -p "$CI_PROJECT_NAME" \
                    down -v --remove-orphans || true

                docker image rm \
                    "${CI_PROJECT_NAME}/eureka-server:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/account-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/foodmaterials-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/menus-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/notices-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/bills-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/purchase-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/disposals-service:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/gateway-server:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/prometheus:${BUILD_NUMBER}" \
                    "${CI_PROJECT_NAME}/grafana:${BUILD_NUMBER}" \
                    || true

                docker volume rm "${CI_PROJECT_NAME}-jwt-public" "${CI_PROJECT_NAME}-jwt-private" || true
                rm -rf secrets/jwt-ci
                rm -f \
                    .env \
                    /tmp/erpmsa-ci-cookie.txt \
                    /tmp/erpmsa-ci-login.json \
                    /tmp/erpmsa-ci-business.json \
                    /tmp/erpmsa-ci-foodmaterial.json \
                    /tmp/erpmsa-ci-foodmaterial-inventory.json \
                    /tmp/erpmsa-ci-prometheus.json
            '''
        }
    }
}
