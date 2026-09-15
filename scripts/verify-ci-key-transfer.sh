#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
project="erpmsa-ci-keycheck-$$"
cleanup() {
  docker volume rm "$project-public" "$project-private" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
"$root/scripts/generate-jwt-keys.sh" ci-k1 "$tmp/jwt"
tar -C "$tmp/jwt/public" -cf - . | docker run --rm -i --network none \
  -v "$project-public:/keys" mariadb:10.11 \
  sh -ec 'tar -xf - -C /keys; chmod 755 /keys; chmod 444 /keys/*.pem'
tar -C "$tmp/jwt/private" -cf - ci-k1.pem | docker run --rm -i --network none \
  -v "$project-private:/keys" mariadb:10.11 \
  sh -ec 'tar -xf - -C /keys; chmod 755 /keys; chmod 444 /keys/*.pem'
docker run --rm --network none --user 1000:1000 \
  -v "$project-public:/run/jwt-public:ro" mariadb:10.11 \
  sh -ec 'test -r /run/jwt-public/ci-k1.pem; test ! -e /run/jwt-private'
docker run --rm --network none --user 1000:1000 \
  -v "$project-public:/run/jwt-public:ro" -v "$project-private:/run/jwt-private:ro" mariadb:10.11 \
  sh -ec 'test -r /run/jwt-public/ci-k1.pem; test -r /run/jwt-private/ci-k1.pem'
echo 'PASS: CI volume transfer and non-root issuer/verifier key permissions'
