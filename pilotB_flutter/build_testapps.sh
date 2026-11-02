#!/usr/bin/env bash
# Build the four Pilot B test-app variants, copy APKs and R8/Dart mapping files into
# pilotB_flutter/apks and pilotB_flutter/mappings, and record hashes in
# results/pilotB/test_apks.csv.
#
# Flutter release builds are not byte-reproducible: a rebuild gives new SHA-256s,
# so analysis outputs that depend on the test APKs must be regenerated afterwards.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
ROOT=$(cd .. && pwd)
JAVA_HOME=${JAVA_HOME:-"/Applications/Android Studio.app/Contents/jbr/Contents/Home"}
export JAVA_HOME
mkdir -p apks mappings "$ROOT/results/pilotB"

# Flutter: default, then --obfuscate (each build overwrites the previous outputs).
cd "$HERE/testapp_flutter"
flutter pub get
flutter build apk --release
cp build/app/outputs/flutter-apk/app-release.apk "$HERE/apks/flutter_default.apk"
cp build/app/outputs/mapping/release/mapping.txt "$HERE/mappings/flutter_default.mapping.txt"
rm -rf build/debug-info
flutter build apk --release --obfuscate --split-debug-info=build/debug-info
cp build/app/outputs/flutter-apk/app-release.apk "$HERE/apks/flutter_obfuscated.apk"
cp build/app/outputs/mapping/release/mapping.txt "$HERE/mappings/flutter_obfuscated.mapping.txt"
rm -rf "$HERE/mappings/flutter_obfuscated_debug_info"
cp -r build/debug-info "$HERE/mappings/flutter_obfuscated_debug_info"

# Native: without R8 (template default), then with R8.
cd "$HERE/testapp_native"
./gradlew --no-daemon clean assembleRelease
cp app/build/outputs/apk/release/app-release.apk "$HERE/apks/native.apk"
./gradlew --no-daemon clean assembleRelease -Ppilot.minify=true
cp app/build/outputs/apk/release/app-release.apk "$HERE/apks/native_r8.apk"
cp app/build/outputs/mapping/release/mapping.txt "$HERE/mappings/native_r8.mapping.txt"

cd "$ROOT"
{
  echo "variant,apk,bytes,sha256,built_at"
  for v in flutter_default flutter_obfuscated native native_r8; do
    f="pilotB_flutter/apks/$v.apk"
    echo "$v,$f,$(stat -f %z "$f"),$(shasum -a 256 "$f" | cut -d' ' -f1),$(date -u -r "$f" +%Y-%m-%dT%H:%M:%SZ)"
  done
} > results/pilotB/test_apks.csv
cat results/pilotB/test_apks.csv
