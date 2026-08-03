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
                checkout scm
            }
        }

        stage('Prepare') {
            steps {
                withCredentials([
                    string(
                        credentialsId: 'erpmsa-ci-db-password',
                        variable: 'ERPMSA_DB_PASSWORD'
                    ),
                    string(
                        credentialsId: 'erpmsa-ci-jwt-secret',
                        variable: 'ERPMSA_JWT_SECRET'
                    )
                ]) {
                    sh '''
                        set +x
                        umask 077

                        GRAFANA_CI_ADMIN_PASSWORD=$(openssl rand -hex 32)
                        GRAFANA_CI_SECRET_KEY=$(openssl rand -hex 32)

                        {
                            printf 'DB_PASSWORD=%s\\n' "$ERPMSA_DB_PASSWORD"
                            printf 'JWT_SECRET_BASE64=%s\\n' "$ERPMSA_JWT_SECRET"
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
                        mariadb redis eureka-server

                    docker network connect \
                        "${CI_PROJECT_NAME}_default" \
                        erpmsa-jenkins || true
                '''
            }
        }

        stage('Gradle Test') {
            parallel {
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
                            set +x
                            set -a
                            . ./.env
                            set +a

                            DB_URL=jdbc:mariadb://mariadb:3306/mydb \
                            DB_USERNAME=account \
                            REDIS_HOST=redis \
                            REDIS_PORT=6379 \
                            EUREKA_DEFAULT_ZONE=http://eureka-server:8761/eureka \
                            JPA_DDL_AUTO=update \
                            JPA_SHOW_SQL=false \
                            COOKIE_SECURE=false \
                            ./AccountService/gradlew \
                                -p AccountService \
                                test --no-daemon
                        '''
                    }
                }
            }
        }

        stage('Build Images') {
            steps {
                sh '''
                    docker compose \
                        -f compose.yaml \
                        -f compose.ci.yaml \
                        -p "$CI_PROJECT_NAME" \
                        build
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
                            'query=up{job=~"eureka-server|account-service|gateway-server"}' \
                            -o "$PROMETHEUS_FILE" \
                            http://prometheus:9090/api/v1/query; then

                            TARGET_COUNT=$(jq \
                                '[.data.result[] | select(.value[1] == "1")] | length' \
                                "$PROMETHEUS_FILE")
                        fi

                        printf \
                            'Prometheus target check: attempt=%s up=%s/3\n' \
                            "$ATTEMPT" \
                            "$TARGET_COUNT"

                        if [ "$TARGET_COUNT" -eq 3 ]; then
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
                    test "$TARGET_COUNT" -eq 3
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

                    printf \
                        'me=%s refresh=%s logout=%s\\n' \
                        "$ME_STATUS" \
                        "$REFRESH_STATUS" \
                        "$LOGOUT_STATUS"

                    test "$ME_STATUS" = "200"
                    test "$REFRESH_STATUS" = "200"
                    test "$LOGOUT_STATUS" = "204"

                    rm -f \
                        "$COOKIE_FILE" \
                        "$LOGIN_FILE"
                '''
            }
        }
    }

    post {
        always {
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

                rm -f \
                    .env \
                    /tmp/erpmsa-ci-cookie.txt \
                    /tmp/erpmsa-ci-login.json \
                    /tmp/erpmsa-ci-prometheus.json
            '''
        }
    }
}
