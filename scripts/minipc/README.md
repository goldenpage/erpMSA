# 미니PC 운영 설정

`compose.minipc.yaml`로 실행 중인 미니PC(Ubuntu)에 DB 백업과 Docker 로그 제한을 설치한다.
이 폴더를 미니PC에 복사한 뒤 그 폴더에서 실행한다.

```bash
sudo bash install.sh backup   # DB 백업 설치 후 1회 실행 (서비스 중단 없음)
sudo bash install.sh logs     # Docker 로그 제한 후 ERP 컨테이너 재생성 (1~2분 중단)
```

## DB 백업

- `erpmsa-db-backup.sh` → `/usr/local/sbin/erpmsa-db-backup`
- `erpmsa-db-backup.timer`: 매일 03:30, 꺼져 있었으면 다음 부팅 때 실행
- 시스템 DB를 제외한 업무 DB 전체를 `/var/backups/erpmsa/erpmsa-YYYYmmdd-HHMMSS.sql.gz`로 저장
- 비밀번호는 컨테이너의 `MARIADB_ROOT_PASSWORD`를 컨테이너 안에서만 읽는다
- 압축 무결성과 `-- Dump completed` 마지막 줄을 확인한 백업만 남기고 14일이 지난 백업은 삭제
- Redis·Kafka는 백업하지 않는다. 백업은 같은 디스크에 있으므로 주기적으로 다른 장비에 복사한다

수동 실행과 상태 확인:

```bash
sudo systemctl start erpmsa-db-backup.service
journalctl -u erpmsa-db-backup.service -n 20
systemctl list-timers erpmsa-db-backup.timer
```

복원(대상 DB를 덮어쓰므로 확인 후 실행):

```bash
cd ~/erpMSA
sudo gunzip -c /var/backups/erpmsa/erpmsa-<시각>.sql.gz \
  | sudo docker compose exec -T mariadb sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot'
```

## Docker 로그 제한

`docker-daemon.json` → `/etc/docker/daemon.json` (컨테이너당 20MB × 3개).
기존 `daemon.json`이 다르면 덮어쓰지 않고 중단한다. 새 컨테이너에만 적용되므로 Docker 재시작 후
ERP 컨테이너를 `--force-recreate`로 다시 만든다. 이름 있는 데이터 볼륨은 유지된다.
