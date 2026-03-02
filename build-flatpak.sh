#!/usr/bin/env bash
set -euo pipefail

APP_ID="io.github.exwin"

# Requires:
#   flatpak flatpak-builder
#   flatpak remote: flathub (or any remote providing org.gnome.Platform//48 + Sdk)
#
# One-time setup:
#   flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
#   flatpak install --user flathub org.gnome.Platform//48 org.gnome.Sdk//48
#
# To sideload the resulting bundle:
#   flatpak install --user io.github.exwin.flatpak

echo "Building Flatpak…"
flatpak-builder --user --install --force-clean build-dir "${APP_ID}.yml"

echo "Bundling…"
flatpak build-bundle \
  "${HOME}/.local/share/flatpak/repo" \
  "${APP_ID}.flatpak" \
  "${APP_ID}"

SIZE=$(du -sh "${APP_ID}.flatpak" | cut -f1)
echo "Done: ${APP_ID}.flatpak (${SIZE})"
