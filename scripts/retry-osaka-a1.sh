#!/usr/bin/env bash
# Run in the Osaka home region's authenticated OCI Cloud Shell.
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: bash retry-osaka-a1.sh TENANCY_OCID SUBNET_OCID IMAGE_OCID SSH_PUBLIC_KEY [COMPARTMENT_OCID]

Launches erpmsa-01 with 2 OCPUs and 12 GB in ap-osaka-1. Use an existing
public subnet for MSA, the selected Osaka ARM64 image, and an OpenSSH .pub key.
If COMPARTMENT_OCID is omitted, uses the tenancy's root compartment.
Use with enough remaining Always Free compute and boot volume allowance.
Retries host-capacity errors every minute while the session is active.
If OCI rate-limits a launch, waits 5 minutes and doubles the delay on further
rate limits, up to 30 minutes.
Set ERPMSA_A1_MAX_ATTEMPTS to a positive number to stop after that many tries.
EOF
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  usage
  exit 0
fi
if [[ $# -lt 4 || $# -gt 5 ]]; then
  usage >&2
  exit 2
fi

tenancy=$1
subnet=$2
image=$3
ssh_public_key=$4
compartment=${5:-$tenancy}
region=ap-osaka-1
name=erpmsa-01
max_attempts=${ERPMSA_A1_MAX_ATTEMPTS:-0}
retry_seconds=60

if [[ ! $tenancy =~ ^ocid1\.tenancy\.oc1\.\.[[:alnum:]]+$ ||
      ! $compartment =~ ^ocid1\.(tenancy|compartment)\.oc1\.\.[[:alnum:]]+$ ||
      $subnet != ocid1.subnet.oc1.ap-osaka-1.* ||
      $image != ocid1.image.oc1.ap-osaka-1.* ]]; then
  echo 'Use the tenancy/compartment OCIDs and the Osaka subnet and image OCIDs.' >&2
  exit 2
fi
if ! command -v oci >/dev/null; then
  echo 'OCI CLI is required. Run this in your authenticated OCI Cloud Shell.' >&2
  exit 2
fi
if [[ ! $max_attempts =~ ^(0|[1-9][0-9]{0,5})$ ]]; then
  echo 'ERPMSA_A1_MAX_ATTEMPTS must be 0 or a positive integer of at most six digits.' >&2
  exit 2
fi

oci_osaka() {
  oci --region "$region" --cli-rc-file /dev/null --no-retry \
    --connection-timeout 15 --read-timeout 90 --output json "$@"
}

home_region=$(oci_osaka iam region-subscription list --tenancy-id "$tenancy" \
  --query 'data[?"is-home-region" == `true`]."region-name" | [0]' --raw-output)
if [[ $home_region != "$region" ]]; then
  echo 'Stopped: this tenancy does not have Osaka as its home region.' >&2
  exit 2
fi
availability_domain=$(oci_osaka iam availability-domain list --compartment-id "$tenancy" \
  --query 'data[0].name' --raw-output)
if [[ $availability_domain != *-AD-1 ]]; then
  echo 'Stopped: could not resolve Osaka AD-1.' >&2
  exit 2
fi

state_dir="$HOME/.local/state/erpmsa-a1-retry/${compartment##*.}"
lock_dir="$state_dir/lock"
attempt_record="$state_dir/launch.txt"
mkdir -p "$state_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "Another run owns $lock_dir. Verify its status before clearing the lock." >&2
  exit 1
fi
trap 'rm -f "$lock_dir/public.pub" "$lock_dir/error.log"; rmdir "$lock_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Keep only the public key type and data. Never pass a private key to OCI.
if ! awk 'NR == 1 && ($1 == "ssh-rsa" || $1 == "ssh-ed25519") && NF >= 2 { print $1, $2; ok = 1 } END { if (!ok) exit 1 }' \
  "$ssh_public_key" > "$lock_dir/public.pub" ||
  ! ssh-keygen -l -f "$lock_dir/public.pub" >/dev/null 2>&1; then
  echo 'Provide an OpenSSH RSA or Ed25519 public key file (.pub).' >&2
  exit 2
fi

for ((attempt = 1; max_attempts == 0 || attempt <= max_attempts; attempt++)); do
  existing=$(oci_osaka compute instance list --compartment-id "$compartment" --all \
    --display-name "$name" --query 'data[?"lifecycle-state" != `"TERMINATED"`].id | [0]' --raw-output)
  if [[ $existing == ocid1.instance.* ]]; then
    printf 'Stopped: %s already exists (%s). Check its state in Compute → Instances.\n' "$name" "$existing"
    exit 0
  fi
  if [[ -f $attempt_record ]]; then
    printf 'A previous launch was accepted or its result is unknown. Check Compute → Instances and %s before launching again.\n' \
      "$attempt_record" >&2
    exit 1
  fi

  printf '[%s] Attempt %d: Osaka A1, 2 OCPUs, 12 GB\n' "$(date -u +%FT%TZ)" "$attempt"
  printf 'Launch requested at %s UTC. Result not yet confirmed.\n' "$(date -u +%FT%T)" > "$attempt_record"
  if instance=$(oci_osaka compute instance launch \
    --compartment-id "$compartment" --availability-domain "$availability_domain" \
    --display-name "$name" --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' \
    --subnet-id "$subnet" --assign-public-ip true --image-id "$image" \
    --ssh-authorized-keys-file "$lock_dir/public.pub" \
    --query 'data.id' --raw-output 2> "$lock_dir/error.log"); then
    if [[ $instance != ocid1.instance.* ]]; then
      echo 'Launch returned without an instance OCID. Check Compute → Instances before retrying.' >&2
      exit 1
    fi
    printf 'Accepted instance: %s\n' "$instance" > "$attempt_record"
    printf 'Launch accepted: %s. Confirm Running in Compute → Instances.\n' "$instance"
    exit 0
  fi

  if LC_ALL=C grep -Eq '^[[:space:]]*"status"[[:space:]]*:[[:space:]]*429[[:space:]]*,?[[:space:]]*$' "$lock_dir/error.log" &&
     LC_ALL=C grep -Eq '^[[:space:]]*"code"[[:space:]]*:[[:space:]]*"TooManyRequests"' "$lock_dir/error.log"; then
    retry_seconds=$((retry_seconds < 300 ? 300 : retry_seconds * 2))
    if (( retry_seconds > 1800 )); then
      retry_seconds=1800
    fi
    retry_reason='OCI rate limit (429).'
  elif LC_ALL=C grep -Eiq '^[[:space:]]*"message"[[:space:]]*:[[:space:]]*"[^"]*out of (host )?capacity' "$lock_dir/error.log"; then
    retry_reason='No A1 host capacity.'
  else
    cat "$lock_dir/error.log" >&2
    echo 'Stopped on a non-capacity or uncertain error. Check the instance list before retrying.' >&2
    exit 1
  fi
  rm -f "$attempt_record"
  if (( max_attempts == 0 || attempt < max_attempts )); then
    printf '%s Retrying in %d seconds.\n' "$retry_reason" "$retry_seconds"
    sleep "$retry_seconds"
  fi
done

printf 'No instance created after %d attempts. Last response: %s\n' "$max_attempts" "$retry_reason" >&2
exit 1
