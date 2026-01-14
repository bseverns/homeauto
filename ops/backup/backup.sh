#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/ops/backup/out"

usage() {
  cat <<'USAGE'
Usage: ops/backup/backup.sh [--help]

Creates a timestamped backup archive in ops/backup/out/ containing:
- config/ (service configs)
- data/ (root compose data)
- infra/turingpi2/data/ (Turing Pi slice data)
- docker-compose.yml
- .env (if present)

No secrets are generated here — whatever lives in your .env is what gets archived.
USAGE
}

if [[ ${#} -eq 0 ]]; then
  usage
  printf '\nProceeding with default backup...\n\n'
elif [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

mkdir -p "${OUT_DIR}"

stamp="$(date +"%Y%m%d-%H%M%S")"
archive="${OUT_DIR}/homeauto-backup-${stamp}.tar.gz"

paths=(
  "config"
  "data"
  "infra/turingpi2/data"
  "docker-compose.yml"
)

if [[ -f "${ROOT_DIR}/.env" ]]; then
  paths+=(".env")
fi

printf '➤ Creating backup archive: %s\n' "${archive}"

existing_paths=()
for path in "${paths[@]}"; do
  if [[ -e "${ROOT_DIR}/${path}" ]]; then
    existing_paths+=("${path}")
  else
    printf '  • Skipping missing path: %s\n' "${path}"
  fi
done

if [[ ${#existing_paths[@]} -eq 0 ]]; then
  printf 'No valid paths found to back up. Aborting.\n' >&2
  exit 1
fi

tar -czf "${archive}" -C "${ROOT_DIR}" "${existing_paths[@]}"

printf '✓ Backup complete.\n'
printf '  Archive: %s\n' "${archive}"
