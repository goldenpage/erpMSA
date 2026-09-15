#!/usr/bin/env bash
set -euo pipefail
umask 077
kid="${1:-local-k1}"
directory="${2:-secrets/jwt}"
[[ "$kid" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || { echo 'Invalid kid' >&2; exit 1; }
mkdir -p "$directory/private" "$directory/public"
chmod 700 "$directory/private"
chmod 755 "$directory/public"
private="$directory/private/$kid.pem"
public="$directory/public/$kid.pem"
[[ ! -e "$private" && ! -e "$public" ]] || { echo 'Existing keys are never overwritten.' >&2; exit 1; }
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$private" 2>/dev/null
openssl pkey -in "$private" -pubout -out "$public"
# Compose file secrets use bind mounts and ignore uid/gid remapping. The enclosing
# host private directory stays 0700; only the issuer receives the read-only file.
chmod 444 "$private" "$public"
echo "Created JWT key pair: $kid (private directory access restricted)"
