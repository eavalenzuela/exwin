#!/usr/bin/env bash
# Build an exwin_<ver>_all.deb without debhelper or dh_python3.
#
# Usage: packaging/deb/build-deb.sh [output_dir]
#   output_dir defaults to the repo root.
#
# Output: exwin_<version>_all.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${1:-${REPO_ROOT}}"

VERSION="$(grep -E '^version\s*=' "${REPO_ROOT}/pyproject.toml" | head -n1 \
    | sed -E 's/^version\s*=\s*"([^"]+)".*/\1/')"
if [ -z "${VERSION}" ]; then
    echo "Failed to read version from pyproject.toml" >&2
    exit 1
fi

STAGE="$(mktemp -d /tmp/exwin-deb.XXXXXX)"
trap 'rm -rf "${STAGE}"' EXIT
ROOT="${STAGE}/exwin_${VERSION}_all"

# --- Layout -----------------------------------------------------------------
install -d "${ROOT}/DEBIAN"
install -d "${ROOT}/usr/bin"
install -d "${ROOT}/usr/lib/python3/dist-packages"
install -d "${ROOT}/usr/share/applications"
install -d "${ROOT}/usr/share/metainfo"
install -d "${ROOT}/usr/share/icons/hicolor/scalable/apps"
install -d "${ROOT}/usr/share/doc/exwin"

# --- Python package ---------------------------------------------------------
# Copy the source tree; strip __pycache__ and test/build detritus.
cp -r "${REPO_ROOT}/exwin" "${ROOT}/usr/lib/python3/dist-packages/"
find "${ROOT}/usr/lib/python3/dist-packages/exwin" \
    -type d -name __pycache__ -exec rm -rf {} + || true
find "${ROOT}/usr/lib/python3/dist-packages/exwin" \
    -type f -name '*.pyc' -delete || true

# --- Entry script -----------------------------------------------------------
cat > "${ROOT}/usr/bin/exwin" <<'EOF'
#!/usr/bin/python3
# exwin launcher — installed by the Debian package.
import sys
from exwin.__main__ import main

if __name__ == "__main__":
    sys.exit(main() or 0)
EOF
chmod 0755 "${ROOT}/usr/bin/exwin"

# --- Data files -------------------------------------------------------------
install -m 0644 "${REPO_ROOT}/data/io.github.exwin.desktop" \
    "${ROOT}/usr/share/applications/io.github.exwin.desktop"
install -m 0644 "${REPO_ROOT}/data/io.github.exwin.metainfo.xml" \
    "${ROOT}/usr/share/metainfo/io.github.exwin.metainfo.xml"
install -m 0644 "${REPO_ROOT}/data/icons/hicolor/scalable/apps/io.github.exwin.svg" \
    "${ROOT}/usr/share/icons/hicolor/scalable/apps/io.github.exwin.svg"
install -m 0644 "${REPO_ROOT}/LICENSE" "${ROOT}/usr/share/doc/exwin/copyright"
install -m 0644 "${REPO_ROOT}/README.md" "${ROOT}/usr/share/doc/exwin/README.md"

# --- DEBIAN control + maintainer scripts -----------------------------------
sed -e "s/@VERSION@/${VERSION}/" "${SCRIPT_DIR}/control.in" > "${ROOT}/DEBIAN/control"
install -m 0755 "${SCRIPT_DIR}/postinst" "${ROOT}/DEBIAN/postinst"
install -m 0755 "${SCRIPT_DIR}/postrm" "${ROOT}/DEBIAN/postrm"
# Strip debhelper sentinel lines (we don't run debhelper).
sed -i '/#DEBHELPER#/d' "${ROOT}/DEBIAN/postinst" "${ROOT}/DEBIAN/postrm"

# --- Build ------------------------------------------------------------------
fakeroot dpkg-deb --build --root-owner-group -Zgzip "${ROOT}" \
    > /dev/null

OUT_FILE="${ROOT}.deb"
mkdir -p "${OUT_DIR}"
mv "${OUT_FILE}" "${OUT_DIR}/"
FINAL="${OUT_DIR}/$(basename "${OUT_FILE}")"

SIZE=$(du -h "${FINAL}" | cut -f1)
echo "Built: ${FINAL} (${SIZE})"
