#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/ops/backup/out"

usage() {
  cat <<'USAGE'
Usage: ops/backup/restore-check.sh [--archive path/to/archive.tar.gz]

Validates a backup by listing its contents and extracting it into a temp directory.
No files are restored in-place. This is a safe drill.
USAGE
}

if [[ ${#} -eq 0 ]]; then
  usage
  printf '\nProceeding with latest backup...\n\n'
fi

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

archive=""
if [[ ${1:-} == "--archive" ]]; then
  archive="${2:-}"
fi

if [[ -z "${archive}" ]]; then
  archive="$(ls -1t "${OUT_DIR}"/homeauto-backup-*.tar.gz 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${archive}" || ! -f "${archive}" ]]; then
  printf 'No backup archive found. Run ops/backup/backup.sh first.\n' >&2
  exit 1
fi

printf '➤ Inspecting archive: %s\n' "${archive}"

printf '\n➤ Archive contents (top-level):\n'
tar -tzf "${archive}" | awk -F/ '!seen[$1]++ {print "  • " $1}'

tmp_dir="$(mktemp -d -t homeauto-restore-check-XXXX)"

printf '\n➤ Extracting to temp dir: %s\n' "${tmp_dir}"
tar -xzf "${archive}" -C "${tmp_dir}"

printf '\n✓ Restore drill complete. Inspect files in: %s\n' "${tmp_dir}"
printf '  When done, delete with: rm -rf %s\n' "${tmp_dir}"
