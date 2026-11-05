#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
WORK_DIR=$(mktemp -d)
trap 'rm -rf -- "$WORK_DIR"' EXIT
GATEWAY_URL=${GATEWAY_URL:-http://gateway-server:7070}
PROMETHEUS_URL=${PROMETHEUS_URL:-http://prometheus:9090}
GRAFANA_URL=${GRAFANA_URL:-http://grafana:3000}

verify_monitoring() {
    . ./.env

    PROMETHEUS_FILE="$WORK_DIR/prometheus.json"
    TARGET_COUNT=0

    PROMETHEUS_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -o /dev/null \
        -w '%{http_code}' \
        "$PROMETHEUS_URL/-/ready")

    GRAFANA_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -o /dev/null \
        -w '%{http_code}' \
        "$GRAFANA_URL/api/health")

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
            "$PROMETHEUS_URL/api/v1/query"; then

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
        "$GRAFANA_URL/api/search?query=ErpMSA%20Spring%20Services" \
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
}

verify_api() {
    : "${BUILD_NUMBER:?BUILD_NUMBER is required}"
    COOKIE_FILE="$WORK_DIR/cookie.txt"
    LOGIN_FILE="$WORK_DIR/login.json"
    FOOD_MATERIAL_FILE="$WORK_DIR/foodmaterial.json"
    BUSINESS_ID=$(printf '%010d' "$BUILD_NUMBER")
    TEST_EMAIL="ci-${BUILD_NUMBER}@example.com"

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
            "$GATEWAY_URL/account/auth/login" \
            || true)

        printf \
            'Gateway route check: attempt=%s status=%s\n' \
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
            'Gateway 라우팅 준비 실패: 마지막 HTTP 상태=%s\n' \
            "$ROUTE_STATUS"
        exit 1
    fi

    NO_TOKEN_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -o /dev/null \
        -w '%{http_code}' \
        "$GATEWAY_URL/account/auth/me")

    REGISTER_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -o /dev/null \
        -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -d "{
            \"email\": \"${TEST_EMAIL}\",
            \"businessId\": \"${BUSINESS_ID}\",
            \"password\": \"Test1234!\",
            \"name\": \"CI Test\",
            \"phone\": \"01000000000\",
            \"storeName\": \"CI Store\",
            \"storeType\": \"RETAIL\",
            \"storeCategory\": \"TEST\",
            \"marketingAgreed\": false
        }" \
        "$GATEWAY_URL/account/auth/register")

    LOGIN_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -c "$COOKIE_FILE" \
        -o "$LOGIN_FILE" \
        -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -d "{
            \"email\": \"${TEST_EMAIL}\",
            \"password\": \"Test1234!\"
        }" \
        "$GATEWAY_URL/account/auth/login")

    printf \
        'route=%s no_token=%s register=%s login=%s\n' \
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
                -o "$WORK_DIR/service-contract.json" -w '%{http_code}' \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "$GATEWAY_URL/$SERVICE_PATH" || true)
            if [ "$SHELL_STATUS" = "501" ]; then break; fi
            sleep 2
        done
        test "$SHELL_STATUS" = "501"
        test "$(jq -r '.code' "$WORK_DIR/service-contract.json")" = "ENDPOINT_NOT_IMPLEMENTED"
    done
    rm -f "$WORK_DIR/service-contract.json"

    FOOD_MATERIAL_ROUTE_STATUS=000

    for ATTEMPT in $(seq 1 30); do
        FOOD_MATERIAL_ROUTE_STATUS=$(curl \
            -sS \
            --connect-timeout 2 \
            --max-time 5 \
            -o /dev/null \
            -w '%{http_code}' \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            "$GATEWAY_URL/foodmaterials" \
            || true)

        printf \
            'FoodMaterials route check: attempt=%s status=%s\n' \
            "$ATTEMPT" \
            "$FOOD_MATERIAL_ROUTE_STATUS"

        if [ "$FOOD_MATERIAL_ROUTE_STATUS" = "200" ]; then
            break
        fi

        sleep 2
    done

    test "$FOOD_MATERIAL_ROUTE_STATUS" = "200"

    FOOD_MATERIAL_BODY=$(jq -nc \
        --arg sku "CI-$BUILD_NUMBER" \
        '{
            sku: $sku,
            name: "CI FoodMaterial",
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
        "$GATEWAY_URL/foodmaterials")

    FOOD_MATERIAL_ID=$(jq -r '.foodMaterialId // empty' "$FOOD_MATERIAL_FILE")
    printf 'FoodMaterial create status=%s\n' "$FOOD_MATERIAL_CREATE_STATUS"

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
        "$GATEWAY_URL/foodmaterials/$FOOD_MATERIAL_ID")

    INVENTORY_FILE="$WORK_DIR/foodmaterial-inventory.json"
    STOCK_BODY=$(jq -nc --argjson id "$FOOD_MATERIAL_ID" '{foodMaterialId:$id,initialQuantity:20}')
    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
        -o "$INVENTORY_FILE" -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
        --data "$STOCK_BODY" "$GATEWAY_URL/foodmaterials/inventories")
    printf 'Inventory create status=%s\n' "$STOCK_STATUS"
    test "$STOCK_STATUS" = "201"
    STOCK_VERSION=$(jq -er '.version' "$INVENTORY_FILE")
    STOCK_BODY=$(jq -nc --argjson version "$STOCK_VERSION" --arg id "CI-STOCK-$BUILD_NUMBER" \
        '{requestId:$id,quantityDelta:-3,reason:"CI smoke",version:$version}')
    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
        -o "$INVENTORY_FILE" -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
        --data "$STOCK_BODY" "$GATEWAY_URL/foodmaterials/inventories/$FOOD_MATERIAL_ID/adjustments")
    printf 'Inventory adjustment status=%s\n' "$STOCK_STATUS"
    test "$STOCK_STATUS" = "200"
    test "$(jq -er '.inventory.onHandQuantity' "$INVENTORY_FILE")" = "17"
    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
        -o "$INVENTORY_FILE" -w '%{http_code}' -H "Authorization: Bearer $ACCESS_TOKEN" \
        "$GATEWAY_URL/foodmaterials/inventories/$FOOD_MATERIAL_ID/movements")
    printf 'Inventory movements status=%s\n' "$STOCK_STATUS"
    test "$STOCK_STATUS" = "200"
    test "$(jq -er '.totalElements' "$INVENTORY_FILE")" = "2"
    rm -f "$INVENTORY_FILE"

    BUSINESS_FILE="$WORK_DIR/business.json"
    # Health checks can pass before Gateway refreshes its Eureka registry.
    for SERVICE_PATH in menus disposals; do
        BUSINESS_ROUTE_STATUS=000
        for ATTEMPT in $(seq 1 45); do
            BUSINESS_ROUTE_STATUS=$(curl -sS --connect-timeout 2 --max-time 5 \
                -o /dev/null -w '%{http_code}' \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "$GATEWAY_URL/$SERVICE_PATH" || true)
            printf 'Business route check: service=%s attempt=%s status=%s\n' \
                "$SERVICE_PATH" "$ATTEMPT" "$BUSINESS_ROUTE_STATUS"
            if [ "$BUSINESS_ROUTE_STATUS" = "200" ]; then break; fi
            sleep 2
        done
        test "$BUSINESS_ROUTE_STATUS" = "200"
    done

    MENU_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o "$BUSINESS_FILE" -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
        --data '{"name":"CI menu","price":12000}' "$GATEWAY_URL/menus")
    printf 'Menu create status=%s\n' "$MENU_STATUS"
    test "$MENU_STATUS" = "201"
    MENU_ID=$(jq -er '.menuId' "$BUSINESS_FILE")
    MENU_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" -X DELETE "$GATEWAY_URL/menus/$MENU_ID")
    printf 'Menu delete status=%s\n' "$MENU_STATUS"
    test "$MENU_STATUS" = "204"
    DISPOSAL_BODY=$(jq -nc --arg id "CI-DISPOSAL-$BUILD_NUMBER" --argjson material "$FOOD_MATERIAL_ID" \
        '{requestId:$id,foodMaterialId:$material,quantity:2,reason:"CI disposal"}')
    for REPLAY in 1 2; do
        DISPOSAL_STATUS=$(curl -sS --connect-timeout 2 --max-time 15 -o "$BUSINESS_FILE" -w '%{http_code}' \
            -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
            --data "$DISPOSAL_BODY" "$GATEWAY_URL/disposals")
        printf 'Disposal replay=%s http=%s state=%s\n' "$REPLAY" "$DISPOSAL_STATUS" "$(jq -r '.status // .code // "unknown"' "$BUSINESS_FILE")"
        test "$DISPOSAL_STATUS" = "200"
        test "$(jq -r '.status' "$BUSINESS_FILE")" = "COMPLETED"
        test "$(jq -r '.quantityAfter' "$BUSINESS_FILE")" = "15"
    done
    STOCK_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 -o "$BUSINESS_FILE" -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" "$GATEWAY_URL/foodmaterials/inventories/$FOOD_MATERIAL_ID")
    test "$STOCK_STATUS" = "200"
    test "$(jq -r '.onHandQuantity' "$BUSINESS_FILE")" = "15"
    rm -f "$BUSINESS_FILE"

    for LEGACY_PATH in items inventories orders; do
        LEGACY_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
            -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            "$GATEWAY_URL/$LEGACY_PATH")
        test "$LEGACY_STATUS" = "404"
    done

    ME_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -o /dev/null \
        -w '%{http_code}' \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        "$GATEWAY_URL/account/auth/me")

    REFRESH_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -b "$COOKIE_FILE" \
        -c "$COOKIE_FILE" \
        -o /dev/null \
        -w '%{http_code}' \
        -X POST \
        "$GATEWAY_URL/account/auth/refresh")

    LOGOUT_STATUS=$(curl \
        -sS \
        --connect-timeout 2 \
        --max-time 10 \
        -b "$COOKIE_FILE" \
        -o /dev/null \
        -w '%{http_code}' \
        -X POST \
        "$GATEWAY_URL/account/auth/logout")

    AFTER_LOGOUT_STATUS=$(curl -sS --connect-timeout 2 --max-time 10 \
        -b "$COOKIE_FILE" -o /dev/null -w '%{http_code}' -X POST \
        "$GATEWAY_URL/account/auth/refresh")
    test "$AFTER_LOGOUT_STATUS" = "401"

    printf \
        'foodmaterials_route=%s foodmaterials_create=%s foodmaterials_get=%s me=%s refresh=%s logout=%s\n' \
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
    echo 'PASS: Gateway authentication, business APIs and service contracts.'
}

ci_compose() {
    : "${CI_PROJECT_NAME:?CI_PROJECT_NAME is required}"
    if [[ "$CI_PROJECT_NAME" != erpmsa-ci-* ]]; then
        echo 'Kafka smoke requires a dedicated CI Compose project.' >&2
        return 1
    fi
    docker compose -f compose.yaml -f compose.ci.yaml -p "$CI_PROJECT_NAME" "$@"
}

outbox_query() {
    ci_compose exec -T mariadb sh -ec '
        MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb --host=127.0.0.1 --user=root \
            --batch --skip-column-names --execute="$1"
    ' sh "$1"
}

verify_kafka() {
    local attempt counts published pending row event_id account_id topic record
    for attempt in {1..30}; do
        counts=$(outbox_query "SELECT COUNT(CASE WHEN status = 'PUBLISHED' THEN 1 END),
            COUNT(CASE WHEN status <> 'PUBLISHED' THEN 1 END) FROM mydb.account_outbox_event;")
        read -r published pending <<< "$counts"
        printf 'Kafka outbox check: attempt=%s published=%s pending=%s\n' "$attempt" "$published" "$pending"
        if [[ "$published" == 1 && "$pending" == 0 ]]; then
            break
        fi
        sleep 2
    done
    [[ "$published" == 1 && "$pending" == 0 ]]

    row=$(outbox_query "SELECT event_id, aggregate_id, topic FROM mydb.account_outbox_event WHERE status = 'PUBLISHED';")
    read -r event_id account_id topic <<< "$row"
    record=$(ci_compose exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh \
        --bootstrap-server kafka:9092 --topic "$topic" --from-beginning --max-messages 1 --timeout-ms 20000)
    jq -e --arg event "$event_id" --arg account "$account_id" \
        '.eventId == $event and (.accountId | tostring) == $account and .eventVersion == 1' <<< "$record" >/dev/null
    echo 'PASS: Kafka record matches the published account outbox event.'
}

case "${1:-}" in
    monitoring) verify_monitoring ;;
    api) verify_api ;;
    kafka) verify_kafka ;;
    *) echo "Usage: $0 {monitoring|api|kafka}" >&2; exit 2 ;;
esac
