#!/usr/bin/env bash
# Scarica il connettore ufficiale bloccato a una versione e ne verifica SHA-256.
set -euo pipefail

PLATFORM="${1:?Piattaforma mancante}"
DEST="${2:?Destinazione mancante}"
VERSION="2026.8.2"
BASE_URL="https://github.com/cloudflare/cloudflared/releases/download/$VERSION"
TEMP_ROOT="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "$TEMP_ROOT/kreluna-cloudflared.XXXXXX")"

cleanup() {
  if [[ -n "$WORK" && "$WORK" == "$TEMP_ROOT"/kreluna-cloudflared.* ]]; then
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

case "$PLATFORM" in
  macos-arm64)
    ASSET="cloudflared-darwin-arm64.tgz"
    EXPECTED="9042c2c5d8b2de78e60f313d5fb31b6c5c1cebde787a3caf1f2c9588084ac442"
    ;;
  windows-x64)
    ASSET="cloudflared-windows-amd64.exe"
    EXPECTED="c29eee2b121f5436a642eed69fd9767da7e7b8c510fa50aaa130337f931357b5"
    ;;
  *)
    echo "Piattaforma cloudflared non supportata: $PLATFORM" >&2
    exit 1
    ;;
esac

curl --fail --location --retry 3 --silent --show-error "$BASE_URL/$ASSET" -o "$WORK/$ASSET"
ACTUAL="$(shasum -a 256 "$WORK/$ASSET" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "Checksum cloudflared non valido: atteso $EXPECTED, ricevuto $ACTUAL" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
if [[ "$PLATFORM" == "macos-arm64" ]]; then
  tar -xzf "$WORK/$ASSET" -C "$WORK"
  cp "$WORK/cloudflared" "$DEST"
  chmod 755 "$DEST"
else
  cp "$WORK/$ASSET" "$DEST"
fi

echo "cloudflared $VERSION verificato: $DEST"
