#!/usr/bin/env bash
set -euo pipefail

project=${CI_PROJECT_NAME:?CI_PROJECT_NAME is required}
kid=${1:?Key ID is required}
key_dir=${2:?Key directory is required}

if [[ "$project" != erpmsa-ci-* ]]; then
    echo 'JWT fixtures require a dedicated CI Compose project.' >&2
    exit 1
fi

# The Docker daemon can run outside the CI workspace (for example, Jenkins on Docker Desktop).
for scope in public private; do
    volume="$project-jwt-$scope"
    docker volume create --label "com.docker.compose.project=$project" \
        --label "com.docker.compose.volume=ci-jwt-$scope" "$volume" >/dev/null
    tar -C "$key_dir/$scope" -cf - "$kid.pem" | docker run --rm -i --network none \
        -v "$volume:/keys" mariadb:10.11 \
        sh -ec 'tar -xf - -C /keys; chmod 755 /keys; chmod 444 /keys/*.pem'
done
