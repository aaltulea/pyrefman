#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

RUNTIME_DIR="$SCRIPT_DIR/.runtime"
UV_DIR="$RUNTIME_DIR/uv"
UV_BIN="$UV_DIR/uv"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
INTERNET_RETRY_TIMEOUT_S=300
INTERNET_RETRY_DELAY_S=5

pause_and_exit() {
  local exit_code="$1"
  echo
  read -r -p "Press Enter to close..."
  exit "$exit_code"
}

text_looks_like_internet_error() {
  local text
  text="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$text" in
    *"unable to connect to the remote server"*|*"could not resolve host"*|*"temporary failure in name resolution"*|*"name or service not known"*|*"no such host is known"*|*"network is unreachable"*|*"connection refused"*|*"connection reset"*|*"connection aborted"*|*"timed out"*|*"timeout"*|*"failed to download"*|*"forbidden by its access permissions"*|*"eacces"*|*"ssl handshake"*|*"tls handshake"*)
      return 0
      ;;
  esac
  return 1
}

run_with_internet_retry() {
  local step_name="$1"
  shift

  local deadline=$((SECONDS + INTERNET_RETRY_TIMEOUT_S))
  local attempt=1

  while true; do
    local output_file
    output_file="$(mktemp)"
    if "$@" >"$output_file" 2>&1; then
      cat "$output_file"
      rm -f "$output_file"
      return 0
    fi

    local output
    output="$(cat "$output_file")"
    rm -f "$output_file"
    printf '%s\n' "$output"

    if ! text_looks_like_internet_error "$output"; then
      return 1
    fi

    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "[ERROR] $step_name kept failing due to missing internet access or a firewall block for 5 minutes." >&2
      return 1
    fi

    local remaining=$((deadline - SECONDS))
    echo "[WARNING] $step_name appears blocked by missing internet access or a firewall rule. Retrying in $INTERNET_RETRY_DELAY_S seconds (attempt $attempt, up to ${remaining}s remaining)..."
    sleep "$INTERNET_RETRY_DELAY_S"
    attempt=$((attempt + 1))
  done
}

install_uv_impl() {
  mkdir -p "$UV_DIR"
  export UV_UNMANAGED_INSTALL="$UV_DIR"
  local installer
  installer="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh -o "$installer"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$installer" https://astral.sh/uv/install.sh
  else
    rm -f "$installer"
    echo "curl or wget is required to bootstrap uv."
    return 1
  fi

  sh "$installer"
  local status=$?
  rm -f "$installer"
  return "$status"
}

if [ ! -x "$UV_BIN" ]; then
  echo "Installing local uv..."
  run_with_internet_retry "Installing local uv" install_uv_impl || pause_and_exit 1
fi

export UV_CACHE_DIR="$RUNTIME_DIR/uv-cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python"
export PLAYWRIGHT_BROWSERS_PATH="$SCRIPT_DIR/.playwright"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Creating project virtual environment..."
  run_with_internet_retry "Creating the project virtual environment" \
    "$UV_BIN" venv "$SCRIPT_DIR/.venv" --python 3.12 --seed || pause_and_exit 1
fi

"$VENV_PYTHON" "$SCRIPT_DIR/scripts/launch.py"
EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
  pause_and_exit "$EXIT_CODE"
fi

exit 0
