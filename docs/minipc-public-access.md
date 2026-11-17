# 미니PC 외부 공개 (Cloudflare Tunnel)

미니PC에서 `compose.minipc.yaml`로 실행 중인 ErpMSA를 `https://<서브도메인>.<도메인>`으로 공개한다.
공유기 포트포워딩은 사용하지 않는다. 미니PC가 Cloudflare로 나가는 연결만 만든다.

```
사용자 ─HTTPS→ Cloudflare ─터널→ cloudflared(컨테이너) ─HTTP→ gateway-server:7070 → 업무 서비스
```

- 공개하는 경로는 Gateway 업무 경로 7개뿐이다. `/actuator` 등 나머지 경로는 Cloudflare에서 404로 끝난다.
- MariaDB·Redis·Kafka·Eureka·Prometheus·Grafana는 기존처럼 `127.0.0.1`에만 열려 있다.
- Gateway는 터널 전용 네트워크(`172.30.250.0/24`)에서 온 연결만 프록시로 믿고 `X-Forwarded-For`에서 실제 접속자
  주소를 읽는다. 이 설정이 없으면 로그인·가입 시도 제한이 모든 사용자를 터널 주소 하나로 센다.

## 1. 도메인 준비

도메인의 DNS가 Cloudflare에 있어야 한다. 다른 등록업체에서 산 도메인이면 Cloudflare에 사이트를 추가하고
등록업체에서 네임서버를 Cloudflare가 알려준 값으로 바꾼다. 상태가 Active가 된 뒤 진행한다.

## 2. 터널 만들기 (Cloudflare 대시보드)

대시보드 메뉴 이름은 바뀔 수 있다.

1. Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared
2. 이름은 예를 들어 `erpmsa-minipc`
3. 설치 안내 화면의 명령에서 `--token` 뒤의 긴 값만 복사한다. 설치 명령은 실행하지 않는다(컨테이너로 실행한다).
4. Public hostname 추가

| 항목 | 값 |
|---|---|
| Subdomain | 예: `erp` |
| Domain | 보유한 도메인 |
| Path | `^/(account\|menus\|foodmaterials\|notices\|bills\|purchase\|disposals)(/\|$)` |
| Service | `HTTP` / `gateway-server:7070` |

Path 칸에는 표의 이스케이프(`\|`)를 빼고 `^/(account|menus|foodmaterials|notices|bills|purchase|disposals)(/|$)`를 입력한다.
규칙에 맞지 않는 요청은 터널 기본 동작으로 404가 된다.

토큰은 터널 전체 권한이다. Git·채팅·이미지에 넣지 않는다. 노출되면 대시보드에서 토큰을 재발급한다.

## 3. 미니PC 설정

`~/erpMSA/.env`에 추가·변경한다.

```bash
CLOUDFLARE_TUNNEL_TOKEN=<복사한 토큰>
COOKIE_SECURE=true
```

`COOKIE_SECURE=true`이면 리프레시 토큰 쿠키가 HTTPS에서만 전달된다. 내부망 `http://<미니PC>:7070`에서는
브라우저가 리프레시 쿠키를 저장하지 않으므로 로그인 갱신은 공개 주소로 확인한다.

## 4. 실행

```bash
cd ~/erpMSA
git pull
sudo docker compose -f compose.yaml -f compose.minipc.yaml -f compose.tunnel.yaml up -d --build --wait
sudo docker compose -f compose.yaml -f compose.minipc.yaml -f compose.tunnel.yaml logs --tail 20 cloudflared
```

로그에 `Registered tunnel connection`이 보이면 연결된 것이다. 이후 실행·재배포 명령에도 세 파일을 모두 지정한다.
`compose.tunnel.yaml`을 빼고 실행하면 Gateway의 프록시 신뢰 설정이 빠진다.

## 5. 확인

```bash
curl -i https://<서브도메인>.<도메인>/actuator/health   # 404여야 한다
curl -i https://<서브도메인>.<도메인>/account/         # Gateway·AccountService 응답(404가 아닌 애플리케이션 응답)
```

Cloudflare 대시보드의 터널 상태가 Healthy인지 확인한다.

## 6. 접속자 제한 (선택)

주소를 아는 누구나 회원가입을 시도할 수 있다. 특정 사람만 쓰게 하려면 Zero Trust → Access → Applications에서
공개 주소에 대한 Self-hosted 애플리케이션을 만들고 허용할 이메일을 정한다.
브라우저가 아닌 API 클라이언트(Postman, 다른 서버)는 Access 로그인 화면을 통과하지 못하므로 Service Token을 따로 발급한다.

## 7. 공개 중지

```bash
sudo docker compose -f compose.yaml -f compose.minipc.yaml up -d --wait --remove-orphans
```

`cloudflared` 컨테이너가 제거되고 Gateway가 프록시 신뢰 설정 없이 다시 만들어진다. 대시보드에서 터널도 삭제할 수 있다.
`.env`의 `COOKIE_SECURE`는 내부망만 쓸 때 `false`로 되돌린다.

## 범위 밖

- 다른 도메인에서 동작하는 웹 프론트엔드가 이 API를 호출하려면 Gateway CORS와 리프레시 쿠키
  `SameSite=Strict`·`path=/account/auth` 정책을 따로 검토해야 한다. 현재 Gateway에는 CORS 설정이 없다.
- Grafana·Prometheus는 공개하지 않는다. SSH 터널로 본다.
