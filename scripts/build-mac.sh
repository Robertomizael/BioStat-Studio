#!/bin/bash
set -euo pipefail

ARCH="${1:-arm64}"
if [[ "$ARCH" != "arm64" && "$ARCH" != "x64" ]]; then
  echo "Arquitectura no válida: $ARCH (use arm64 o x64)" >&2
  exit 2
fi

VERSION="$(node -p "require('./package.json').version")"
PRODUCT="BioStat Studio"

rm -rf dist
mkdir -p dist

# 1) Construir el bundle .app sin crear todavía el DMG.
npx electron-builder --mac dir --"$ARCH" --publish never

# electron-builder usa dist/mac-arm64 para Apple Silicon y dist/mac para Intel.
if [[ "$ARCH" == "arm64" ]]; then
  APP="dist/mac-arm64/${PRODUCT}.app"
  LABEL="arm64"
else
  APP="dist/mac/${PRODUCT}.app"
  LABEL="x64"
fi

if [[ ! -d "$APP" ]]; then
  echo "No se encontró la aplicación construida: $APP" >&2
  find dist -maxdepth 3 -print || true
  exit 3
fi

# 2) Eliminar atributos extendidos heredados y asegurar permisos del motor nativo.
xattr -cr "$APP" || true
IMPORTER="$APP/Contents/Resources/importer/biostat-importer"
if [[ -f "$IMPORTER" ]]; then
  chmod +x "$IMPORTER"
  codesign --force --sign - "$IMPORTER"
fi

# 3) Firma ad-hoc del paquete completo. Esto evita que macOS lo interprete como
#    un bundle alterado/inválido cuando no existe aún un certificado Developer ID.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

# 4) Crear el DMG a partir del .app ya firmado.
STAGE="dist/dmg-${LABEL}"
rm -rf "$STAGE"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/${PRODUCT}.app"
ln -s /Applications "$STAGE/Applications"

OUT="dist/BioStat-Studio-${VERSION}-macOS-${LABEL}.dmg"
hdiutil create \
  -volname "BioStat Studio ${VERSION}" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDZO \
  "$OUT"

# Firma ad-hoc también de la imagen de disco.
codesign --force --sign - "$OUT" || true

# Verificaciones útiles para el log de GitHub Actions.
echo "Instalador generado: $OUT"
ls -lh "$OUT"
spctl --assess --type execute --verbose=4 "$APP" || true
