#!/usr/bin/env bash
# ErpMSA MariaDB 논리 백업. 미니PC에서 root(systemd timer)로 실행한다.
# 비밀번호는 컨테이너의 MARIADB_ROOT_PASSWORD를 컨테이너 안에서만 읽고 파일·인자에 남기지 않는다.
# 성공한 백업만 남기며, KEEP_DAYS보다 오래된 이 스크립트의 백업 파일만 삭제한다.
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/var/backups/erpmsa}"
KEEP_DAYS="${KEEP_DAYS:-14}"
PROJECT="${COMPOSE_PROJECT:-erpmsa}"

[[ "$KEEP_DAYS" =~ ^[0-9]+$ ]] || { echo "KEEP_DAYS는 숫자여야 합니다: $KEEP_DAYS" >&2; exit 1; }

cid="$(docker ps -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter "label=com.docker.compose.service=mariadb")"
[[ -n "$cid" ]] || { echo "실행 중인 $PROJECT mariadb 컨테이너가 없습니다." >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# 시스템 DB를 제외한 업무 DB 전체(mydb, itemdb, inventorydb, menusdb, disposalsdb 등)
dbs="$(docker exec "$cid" sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot -N -B -e "SHOW DATABASES"' \
  | grep -v -x -E 'information_schema|performance_schema|mysql|sys' || true)"
[[ -n "$dbs" ]] || { echo "백업할 DB가 없습니다." >&2; exit 1; }

stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/erpmsa-$stamp.sql.gz"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT

# shellcheck disable=SC2086  # DB 이름은 공백 없는 식별자
docker exec "$cid" sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump -uroot \
     --single-transaction --routines --triggers --events --hex-blob \
     --default-character-set=utf8mb4 --databases "$@"' sh $dbs \
  | gzip -c > "$tmp"

# 압축 손상과 덤프 중단 여부 확인
gzip -t "$tmp"
gzip -dc "$tmp" | tail -n 1 | grep -q '^-- Dump completed' \
  || { echo "덤프가 끝까지 기록되지 않았습니다." >&2; exit 1; }

mv "$tmp" "$out"
trap - EXIT

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'erpmsa-*.sql.gz' -mtime +"$KEEP_DAYS" -delete

echo "백업 완료: $out ($(du -h "$out" | cut -f1)), DB: $(echo $dbs | tr ' ' ',')"
