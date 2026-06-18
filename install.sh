#!/usr/bin/env bash
set -euo pipefail

main() {
  # PowerShell equivalent for Windows is planned.
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Aphrodite needs Python 3.10 or newer." >&2
    echo "Please install python3, then run this installer again." >&2
    exit 1
  fi

  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "Aphrodite needs Python 3.10 or newer." >&2
    echo "Please upgrade python3, then run this installer again." >&2
    exit 1
  fi

  if ! python3 -c 'import venv' >/dev/null 2>&1; then
    echo "Aphrodite needs Python venv support before it can create its private environment." >&2
    case "$(uname -s)" in
      Darwin)
        echo "On macOS with Homebrew, run: brew install python" >&2
        ;;
      Linux)
        echo "On Debian/Ubuntu, run: sudo apt install python3-venv" >&2
        ;;
      *)
        echo "Install the Python venv package for your OS, then run this installer again." >&2
        ;;
    esac
    exit 1
  fi

  local INSTALL_ROOT="${APHRODITE_HOME:-$HOME/.local/share/aphrodite}"
  local VENV="$INSTALL_ROOT/venv"
  local BIN_DIR="${APHRODITE_BIN_DIR:-$HOME/.local/bin}"
  local BIN="$BIN_DIR/aphrodite"
  local CONFIG_DIR="$HOME/.config/aphrodite"
  local CACHE_DIR="$HOME/.cache/aphrodite"
  local PACKAGE_SPEC="aphrodite-sidecar[mcp,acp] @ git+https://github.com/Advenaa/aphrodite"

  mkdir -p "$INSTALL_ROOT" "$BIN_DIR" "$CONFIG_DIR" "$CACHE_DIR"

  if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating Aphrodite Python environment..."
    python3 -m venv "$VENV"
  fi

  echo "Installing or updating Aphrodite..."
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

  local tmp
  tmp="$(mktemp "$BIN_DIR/.aphrodite.XXXXXX")"
  trap 'rm -f "$tmp"' EXIT

  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'VENV=%q\n' "$VENV"
    printf '%s\n' 'exec "$VENV/bin/python" -m aphrodite.cli "$@"'
  } >"$tmp"
  chmod +x "$tmp"
  mv "$tmp" "$BIN"
  trap - EXIT

  "$BIN" version 2>/dev/null || true
  echo "Aphrodite is ready."
  case ":$PATH:" in
    *":$BIN_DIR:"*)
      echo "Next: aphrodite serve"
      echo "Then: aphrodite doctor"
      ;;
    *)
      echo "Note: $BIN_DIR is not on your PATH yet." >&2
      echo "Add this to your shell profile:" >&2
      echo "  export PATH=\"$BIN_DIR:\$PATH\"" >&2
      echo "Works right now:" >&2
      echo "  \"$BIN\" serve" >&2
      echo "  \"$BIN\" doctor" >&2
      ;;
  esac
}

main "$@"
