#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required_dirs=(
  "data/homeassistant"
  "data/nodered"
  "data/mosquitto/config"
  "data/mosquitto/data"
  "data/mosquitto/log"
  "data/pihole/etc-pihole"
  "data/pihole/etc-dnsmasq.d"
  "data/unbound"
  "data/snapcast/config"
  "data/snapcast/fifo"
  "data/mopidy"
  "data/librespot/cache"
  "data/octofarm"
  "data/tailscale"
  "data/portainer"
  "config/mopidy"
)

trim() {
  printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

printf '➤ Ensuring volume directories exist...\n'
for dir in "${required_dirs[@]}"; do
  abs_dir="${ROOT_DIR}/${dir}"
  if [[ -d "${abs_dir}" ]]; then
    printf '  • %s (already there)\n' "${dir}"
  else
    mkdir -p "${abs_dir}"
    printf '  • %s (created)\n' "${dir}"
  fi
done

declare -A env_map
ENV_FILE="${ROOT_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line}" ]] && continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    if [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      value="${value%%#*}"
      value="${value%$'\r'}"
      value="$(trim "${value}")"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      env_map["${key}"]="${value}"
    fi
  done < "${ENV_FILE}"
fi

declare -A fifo_targets
fifo_targets[music]="${env_map[MOPIDY_FIFO]:-data/snapcast/fifo/snapfifo_music}"
fifo_targets[spotify]="${env_map[LIBRESPOT_FIFO]:-data/snapcast/fifo/snapfifo_spotify}"

printf '\n➤ Ensuring Snapcast FIFOs exist...\n'
for name in "${!fifo_targets[@]}"; do
  fifo_path="${fifo_targets[$name]}"
  if [[ -z "${fifo_path}" ]]; then
    printf '  • %s FIFO skipped: no path defined\n' "${name}" >&2
    continue
  fi
  if [[ "${fifo_path}" == ~/* ]]; then
    fifo_path="${HOME}/${fifo_path#~/}"
  elif [[ "${fifo_path}" == ~ ]]; then
    fifo_path="${HOME}"
  elif [[ "${fifo_path}" != /* ]]; then
    fifo_path="${ROOT_DIR}/${fifo_path}"
  fi
  fifo_dir="$(dirname "${fifo_path}")"
  mkdir -p "${fifo_dir}"
  if [[ -p "${fifo_path}" ]]; then
    printf '  • %s FIFO at %s (already there)\n' "${name}" "${fifo_path}"
  elif [[ -e "${fifo_path}" ]]; then
    printf '  • %s FIFO skipped: %s exists but is not a FIFO\n' "${name}" "${fifo_path}" >&2
  else
    mkfifo "${fifo_path}"
    chmod 666 "${fifo_path}"
    printf '  • %s FIFO at %s (created)\n' "${name}" "${fifo_path}"
  fi
done

printf '\nDone.\n'
