#!/usr/bin/env bash
# 미니PC 운영 설정 설치. 이 폴더에서 sudo로 실행한다.
#   sudo bash install.sh backup  # DB 백업 스크립트·매일 03:30 타이머 설치 후 1회 실행
#   sudo bash install.sh logs    # Docker 로그 크기 제한 후 ERP 컨테이너 재생성(1~2분 중단)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "sudo로 실행하세요." >&2; exit 1; }
OWNER_HOME="$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)"
ERP_DIR="${ERP_DIR:-$OWNER_HOME/erpMSA}"

install_backup() {
  install -m 0755 -o root -g root "$HERE/erpmsa-db-backup.sh" /usr/local/sbin/erpmsa-db-backup
  install -m 0644 -o root -g root "$HERE/erpmsa-db-backup.service" /etc/systemd/system/erpmsa-db-backup.service
  install -m 0644 -o root -g root "$HERE/erpmsa-db-backup.timer" /etc/systemd/system/erpmsa-db-backup.timer
  systemctl daemon-reload
  systemctl enable --now erpmsa-db-backup.timer
  echo '== 첫 백업 실행'
  systemctl start erpmsa-db-backup.service
  journalctl -u erpmsa-db-backup.service -n 5 --no-pager -o cat
  ls -lh /var/backups/erpmsa/
  systemctl list-timers erpmsa-db-backup.timer --no-pager
}

install_logs() {
  local target=/etc/docker/daemon.json
  if [[ -e "$target" ]] && ! cmp -s "$HERE/docker-daemon.json" "$target"; then
    echo "$target 가 이미 있고 내용이 다릅니다. 덮어쓰지 않습니다." >&2
    cat "$target" >&2
    exit 1
  fi
  [[ -f "$ERP_DIR/compose.minipc.yaml" ]] || { echo "ERP 폴더를 찾지 못했습니다: $ERP_DIR" >&2; exit 1; }
  install -m 0644 -o root -g root "$HERE/docker-daemon.json" "$target"
  dockerd --validate --config-file "$target"
  echo '== Docker 재시작'
  systemctl restart docker
  echo '== ERP 컨테이너 재생성(데이터 볼륨 유지)'
  docker compose --project-directory "$ERP_DIR" \
    -f "$ERP_DIR/compose.yaml" -f "$ERP_DIR/compose.minipc.yaml" \
    up -d --force-recreate --wait
  echo '== 적용 확인'
  docker ps --format '{{.Names}}' | while read -r name; do
    printf '%-40s %s\n' "$name" "$(docker inspect --format '{{.HostConfig.LogConfig.Config}}' "$name")"
  done
}

case "${1:-}" in
  backup) install_backup ;;
  logs) install_logs ;;
  *) echo "사용법: sudo bash install.sh {backup|logs}" >&2; exit 1 ;;
esac
