#!/usr/bin/env bash
# Fetch ClashKing Home Village building sprites (~4.8 MB, 472 WebP).
# Source: https://github.com/ClashKingInc/ClashKingAssets
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/clashking/home-village"
TMP_REPO="${TMPDIR:-/tmp}/ClashKingAssets-sparse-$$"

cleanup() {
  rm -rf "${TMP_REPO}"
}
trap cleanup EXIT

if [[ -d "${DEST}" ]] && find "${DEST}" -name '*.webp' | grep -q .; then
  echo "Sprites already present under ${DEST}"
  find "${DEST}" -name '*.webp' | wc -l | xargs echo "WebP files:"
  exit 0
fi

echo "Sparse-cloning ClashKingAssets (buildings/home-village only)..."
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/ClashKingInc/ClashKingAssets.git "${TMP_REPO}"
(
  cd "${TMP_REPO}"
  git sparse-checkout set assets/buildings/home-village
)

mkdir -p "${SCRIPT_DIR}/clashking"
rm -rf "${DEST}"
mkdir -p "${DEST}"
rsync -a "${TMP_REPO}/assets/buildings/home-village/" "${DEST}/"

count="$(find "${DEST}" -name '*.webp' | wc -l | tr -d ' ')"
size="$(du -sh "${DEST}" | cut -f1)"
echo "Done: ${count} WebP files (${size}) → ${DEST}"
