#!/usr/bin/env bash
# Build the calculation engines used by the platform into engines/lib/.
#
#   EPANET 2.3 – built from THIS repository's own source (src/, include/).
#   EPA SWMM 5.2.4 – fetched from the official USEPA repository at a pinned
#                    tag into engines/.build/ (git-ignored) and built there.
#                    SWMM source is NOT copied into this repository.
#
# Usage:  engines/build_engines.sh            (Linux/macOS; needs git, cmake, a C compiler)
# Windows: run the same steps from a "Developer PowerShell" or use WSL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
LIB="$HERE/lib"
BUILD="$HERE/.build"
SWMM_TAG="${SWMM_TAG:-v5.2.4}"
SWMM_REPO="https://github.com/USEPA/Stormwater-Management-Model"
mkdir -p "$LIB" "$BUILD"

echo "== EPANET (repository source)"
cmake -S "$ROOT" -B "$BUILD/epanet" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$BUILD/epanet" --target epanet2 -j
cp "$BUILD"/epanet/lib/libepanet2.* "$LIB"/ 2>/dev/null || cp "$BUILD"/epanet/bin/*epanet2* "$LIB"/

echo "== EPA SWMM $SWMM_TAG (official source)"
if [ ! -d "$BUILD/swmm-src/.git" ]; then
  git clone --depth 1 --branch "$SWMM_TAG" "$SWMM_REPO" "$BUILD/swmm-src"
fi
cmake -S "$BUILD/swmm-src" -B "$BUILD/swmm" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$BUILD/swmm" --target swmm5 -j
find "$BUILD/swmm" \( -name 'libswmm5.so' -o -name 'libswmm5.dylib' -o -name 'swmm5.dll' \) -exec cp {} "$LIB"/ \;

echo "== Engines in $LIB:"
ls -1 "$LIB"
