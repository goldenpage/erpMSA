pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
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

                        {
                            printf 'DB_PASSWORD=%s\\n' "$ERPMSA_DB_PASSWORD"
                            printf 'JWT_SECRET_BASE64=%s\\n' "$ERPMSA_JWT_SECRET"
                            printf 'JWT_ISSUER=kosta-erp-account\\n'
                            printf 'JWT_AUDIENCE=kosta-erp-api\\n'
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
                            set -a
                            . ./.env
                            set +a

                            DB_URL=jdbc:mariadb://mariadb:3306/mydb \
                            DB_USERNAME=account \
                            REDIS_HOST=redis \
                            REDIS_PORT=6379 \
                            EUREKA_DEFAULT_ZONE=http://eureka-server:8761/eureka \
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

        stage('Authentication Smoke Test') {
            steps {
                sh '''
                    set -eu

                    COOKIE_FILE=/tmp/erpmsa-ci-cookie.txt
                    LOGIN_FILE=/tmp/erpmsa-ci-login.json
                    BUSINESS_ID=$(printf '%010d' "$BUILD_NUMBER")
                    TEST_EMAIL="jenkins-${BUILD_NUMBER}@example.com"

                    NO_TOKEN_STATUS=$(curl -sS \
                        -o /dev/null \
                        -w '%{http_code}' \
                        http://gateway-server:7070/account/auth/me)

                    REGISTER_STATUS=$(curl -sS \
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

                    LOGIN_STATUS=$(curl -sS \
                        -c "$COOKIE_FILE" \
                        -o "$LOGIN_FILE" \
                        -w '%{http_code}' \
                        -H 'Content-Type: application/json' \
                        -d "{
                            \\"email\\": \\"${TEST_EMAIL}\\",
                            \\"password\\": \\"Test1234!\\"
                        }" \
                        http://gateway-server:7070/account/auth/login)

                    ACCESS_TOKEN=$(jq -r '.accessToken // empty' "$LOGIN_FILE")

                    if [ -z "$ACCESS_TOKEN" ]; then
                        echo 'Access Token이 발급되지 않았습니다.'
                        exit 1
                    fi

                    ME_STATUS=$(curl -sS \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -H "Authorization: Bearer $ACCESS_TOKEN" \
                        http://gateway-server:7070/account/auth/me)

                    REFRESH_STATUS=$(curl -sS \
                        -b "$COOKIE_FILE" \
                        -o /dev/null \
                        -w '%{http_code}' \
                        -X POST \
                        http://gateway-server:7070/account/auth/refresh)

                    printf \
                        'no_token=%s register=%s login=%s me=%s refresh=%s\\n' \
                        "$NO_TOKEN_STATUS" \
                        "$REGISTER_STATUS" \
                        "$LOGIN_STATUS" \
                        "$ME_STATUS" \
                        "$REFRESH_STATUS"

                    test "$NO_TOKEN_STATUS" = "401"
                    test "$REGISTER_STATUS" = "201"
                    test "$LOGIN_STATUS" = "200"
                    test "$ME_STATUS" = "200"
                    test "$REFRESH_STATUS" = "200"

                    rm -f "$COOKIE_FILE" "$LOGIN_FILE"
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
                    /tmp/erpmsa-ci-login.json
            '''
        }
    }
}
