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

                        ./scripts/load-ci-jwt-volumes.sh "ci-$BUILD_NUMBER" secrets/jwt-ci

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

        stage('Spring Unit Tests') {
            steps {
                sh '''
                    set -eu
                    set -- --suite unit --source jenkins \
                        --branch "${BRANCH_NAME:-main}" \
                        --run-id "jenkins-${BUILD_NUMBER}"
                    # Optional persistent Pushgateway; do not publish to the disposable CI stack.
                    if [ -n "${SPRING_TEST_PUSHGATEWAY_URL:-}" ]; then
                        set -- "$@" --pushgateway "$SPRING_TEST_PUSHGATEWAY_URL"
                    fi
                    python3 scripts/run-spring-tests.py "$@"
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

        stage('Spring Integration Tests') {
            // Keep one Gradle build active when CI shares Docker Desktop with ERP.
            stages {
                stage('Eureka Integration Test') {
                    steps {
                        sh '''
                            ./eurekaServer/gradlew \
                                -p eurekaServer \
                                integrationTest --no-daemon
                        '''
                    }
                }

                stage('Gateway Integration Test') {
                    steps {
                        sh '''
                            set +x
                            set -a
                            . ./.env
                            set +a

                            EUREKA_DEFAULT_ZONE=http://eureka-server:8761/eureka \
                            ./gatewayServer/gradlew \
                                -p gatewayServer \
                                integrationTest --no-daemon
                        '''
                    }
                }

                stage('Account Integration Test') {
                    steps {
                        sh '''
                            COOKIE_SECURE=false \
                            ./AccountService/gradlew \
                                -p AccountService \
                                integrationTest --no-daemon
                        '''
                    }
                }

                stage('FoodMaterials Integration Test') {
                    steps {
                        sh '''
                            ./FoodMaterialsService/gradlew \
                                -p FoodMaterialsService \
                                integrationTest --no-daemon
                        '''
                    }
                }

                stage('Designed Services Integration Test') {
                    steps {
                        sh '''
                            for SERVICE in MenusService NoticesService BillsService PurchaseService DisposalsService; do
                                ./$SERVICE/gradlew -p "$SERVICE" integrationTest --no-daemon
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
                    docker compose \
                        -f compose.yaml \
                        -f compose.ci.yaml \
                        -p "$CI_PROJECT_NAME" \
                        --parallel 1 build
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
                sh 'scripts/ci-stack-smoke.sh monitoring'
            }
        }

        stage('Authentication Smoke Test') {
            steps {
                sh 'scripts/ci-stack-smoke.sh api'
            }
        }

        stage('Kafka Publish Smoke Test') {
            steps {
                sh 'scripts/ci-stack-smoke.sh kafka'
            }
        }
    }

    post {
        always {
            junit(
                testResults: '**/build/test-results/test/*.xml,**/build/test-results/integrationTest/*.xml',
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
                artifacts: 'compose-ps.txt,compose.log,**/build/reports/tests/**,**/build/reports/jacoco/test/**,.verification/spring-tests/**/summary.json,.verification/spring-tests/**/metrics.prom',
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
                rm -f .env
            '''
        }
    }
}
