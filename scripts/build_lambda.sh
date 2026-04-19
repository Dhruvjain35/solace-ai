#!/usr/bin/env bash
# Build Lambda deployment zip. Cross-compiles wheels for Python 3.11 x86_64 Linux.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BUILD="$ROOT/build/lambda"
ZIP="$ROOT/build/solace-lambda.zip"

echo "→ Cleaning $BUILD"
rm -rf "$BUILD" "$ZIP"
mkdir -p "$BUILD"

echo "→ Installing manylinux wheels for Python 3.12 (app + ML stack)"
python3.11 -m pip install \
  --platform manylinux2014_x86_64 \
  --platform manylinux_2_28_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target "$BUILD" \
  --upgrade \
  --quiet \
  fastapi==0.115.0 \
  mangum==0.17.0 \
  pydantic==2.9.2 \
  pydantic-settings==2.5.2 \
  python-multipart==0.0.10 \
  python-dotenv==1.0.1 \
  openai==1.52.0 \
  anthropic==0.39.0 \
  httpx==0.27.2 \
  starlette==0.38.6 \
  typing-extensions==4.12.2 \
  lightgbm==4.5.0 \
  scikit-learn==1.5.2 \
  pandas==2.2.3 \
  numpy==1.26.4 \
  scipy==1.13.1

echo "→ Bundling libgomp.so.1 (OpenMP runtime for LightGBM on Lambda AL2023)"
LIBGOMP_SRC="$ROOT/build/.cache/libgomp.so.1"
mkdir -p "$(dirname "$LIBGOMP_SRC")"
if [ ! -f "$LIBGOMP_SRC" ]; then
  # Prefer our own S3 mirror (stable), fall back to Debian snapshot
  if aws s3 cp "s3://solace-lambda-deploy-704229156617/libs/libgomp.so.1" "$LIBGOMP_SRC" --quiet 2>/dev/null; then
    echo "  fetched from S3 mirror"
  else
    echo "  S3 mirror unavailable — falling back to Debian snapshot"
    curl -sL -o /tmp/libgomp1.deb "https://snapshot.debian.org/archive/debian/20240101T000000Z/pool/main/g/gcc-12/libgomp1_12.2.0-14_amd64.deb"
    rm -rf /tmp/libgomp-extract && mkdir -p /tmp/libgomp-extract && (cd /tmp/libgomp-extract && ar x /tmp/libgomp1.deb && tar xf data.tar.xz)
    cp /tmp/libgomp-extract/usr/lib/x86_64-linux-gnu/libgomp.so.1 "$LIBGOMP_SRC"
  fi
fi
mkdir -p "$BUILD/lib"
cp "$LIBGOMP_SRC" "$BUILD/lib/libgomp.so.1"
cp "$LIBGOMP_SRC" "$BUILD/libgomp.so.1"  # belt + suspenders — /var/task is on LD path

echo "→ Copying backend source (fold .txt files excluded — fetched from S3 at runtime)"
for dir in db lib routers services; do
  [ -d "$ROOT/backend/$dir" ] && cp -R "$ROOT/backend/$dir" "$BUILD/"
done
cp "$ROOT/backend/main.py" "$BUILD/"
mkdir -p "$BUILD/models"
if [ -f "$ROOT/backend/models/artifacts.pkl" ]; then
  cp "$ROOT/backend/models/artifacts.pkl" "$BUILD/models/"
  echo "  [ok] bundled artifacts.pkl ($(du -k "$ROOT/backend/models/artifacts.pkl" | awk '{print $1}') KB)"
fi

echo "→ Aggressively stripping bloat"
find "$BUILD" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type d -name "*.dist-info" -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type f -name "*.pyc" -delete 2>/dev/null || true
# ML stack bloat
rm -rf "$BUILD"/numpy/tests "$BUILD"/numpy/doc "$BUILD"/numpy/f2py 2>/dev/null || true
rm -rf "$BUILD"/pandas/tests "$BUILD"/pandas/io/tests 2>/dev/null || true
rm -rf "$BUILD"/scipy/tests "$BUILD"/scipy/**/tests 2>/dev/null || true
find "$BUILD"/scipy -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
# Remove scipy submodules not used by our inference or by sklearn internals
# Keep all scipy submodules — sklearn's transitive imports are unpredictable.
# Only strip heavy test/doc/example data which is never loaded at runtime.
rm -rf "$BUILD"/scipy/datasets "$BUILD"/scipy/misc "$BUILD"/scipy/odr 2>/dev/null || true
find "$BUILD"/scipy -type d -name "_examples" -exec rm -rf {} + 2>/dev/null || true
# pandas tz bloat
rm -rf "$BUILD"/pytz/zoneinfo "$BUILD"/tzdata/zoneinfo 2>/dev/null || true
# Keep numpy intact (numpy imports polynomial/distutils at init)
rm -rf "$BUILD"/sklearn/datasets/data "$BUILD"/sklearn/datasets/descr \
       "$BUILD"/sklearn/datasets/images 2>/dev/null || true
find "$BUILD"/sklearn -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
rm -rf "$BUILD"/lightgbm/examples 2>/dev/null || true
# Strip debug symbols from compiled extensions (Linux .so)
find "$BUILD" -type f -name "*.so" -exec strip --strip-unneeded {} \; 2>/dev/null || true
# Delete .pyi/.md from library dirs, but DO NOT touch our models (lgbm_fold*.txt etc)
find "$BUILD" -type f \( -name "*.pyi" -o -name "*.md" \) -not -path "*/models/*" -delete 2>/dev/null || true

echo "→ Zipping → $ZIP"
(cd "$BUILD" && zip -qr9 "$ZIP" .)

SIZE_MB=$(du -m "$ZIP" | awk '{print $1}')
echo "✓ Built $ZIP (${SIZE_MB}MB)"
