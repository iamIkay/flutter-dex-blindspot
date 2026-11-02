# Running log

## 2026-11-01 — Setup + B0

**Environment**
- macOS (arm64). Python 3.13.9 (miniconda) venv at `.venv/`; deps pinned in `requirements.txt`
  (androguard 4.1.4, pandas 3.1.0, pyarrow 26.0.0, requests 2.34.2, PyYAML 6.0.3, tqdm 4.70.1,
  matplotlib 3.11.2, scipy 1.18.1; pypdf installed ad hoc for reading papers).
- Flutter 3.41.2 stable / Dart 3.11.0. Android SDK 36 (build-tools 36.1.0), emulator 37.1.11,
  AVDs available: Medium_Phone_API_36.1, Small_Phone, Pixel_9_Pro_Fold, AndroidWorldAvd.
- JDK: Flutter/Gradle use Android Studio's bundled JBR **21.0.8** (plan said 17; 21 is supported by
  current AGP — decision: use 21, record it). Homebrew OpenJDK 25 is also on PATH; not used for builds.
- `flutter doctor`: only issue is **Android SDK licenses not accepted** — left for John to accept
  (`flutter doctor --android-licenses`), since it is a terms acceptance.
- apktool / jadx not installed yet (needed only for spot checks in B4); will install via Homebrew.
- `common/http.py`: disk cache (`cache/http/`), retry w/ exponential backoff, per-host throttle
  (F-Droid 1 req/s, Semantic Scholar 3 s), GitHub rate-limit sleep when remaining < 50,
  SHA-256 for downloads. Token read from `GITHUB_TOKEN`, never logged or cached.

**B0 novelty check** → `pilotB_flutter/00_novelty_check.md`
- No paper measures detector-feature visibility of Flutter app behaviour. Not a stop condition.
- Closest: Sterling et al., COMPSAC 2026 (MobSF/FlowDroid scores, 1k Flutter/1k RN/1k Kotlin) — abstract only, paywalled.
- Surprise: Semantic Scholar unauthenticated API rate-limits hard (429s); added a 3 s throttle.
- Surprise / correction: the plan's "recall 56–94%" for Tegegn & Rubin is not exact — tool-averaged
  malware recall per split is 52.8–94.0%; per-split F1 is 65.1–93.5%. Details in the novelty file.
- From Tegegn & Rubin Table 2 (read from extracted PDF text): 2 of 25 tools use native code. To be
  verified against the rendered table before quoting.

## 2026-11-01 — B1: test-app pair

**Built** (sources in `pilotB_flutter/testapp_flutter/`, `pilotB_flutter/testapp_native/`; hashes in
`results/pilotB/test_apks.csv`; versions in `pilotB_flutter/ground_truth.json` → `build`):
`flutter_default`, `flutter_obfuscated` (`--obfuscate --split-debug-info`), `native` (no R8, template
default), `native_r8` (R8 on, added to mirror Flutter's default). All signed with the debug keystore.
R8 `mapping.txt` files and Dart obfuscation symbols kept in `pilotB_flutter/mappings/`.

**Decisions / deviations**
- Package names: `com.johnwogu.pilot.flutter` (as planned) and **`com.johnwogu.pilot.nativeapp`**
  (planned `.native` is impossible: `native` is a reserved Java keyword, invalid in a package/R class).
  Flutter project name is `pilot_flutter` (`flutter` is rejected by `flutter create`).
- Native twin uses only platform APIs (plain `android.app.Activity`, `LocationManager` GPS,
  `ContentResolver`+`ContactsContract`, `HttpURLConnection`, `File`), no AndroidX/OkHttp/Play Services.
- Flutter location uses `AndroidSettings(forceLocationManager: true)`. With geolocator's default fused
  provider, Play Services shows a "Location Accuracy" consent dialog; declining makes geolocator
  report "location service disabled", and accepting would consent to Google data collection. Forcing
  LocationManager matches the native twin; both code paths ship in the plugin's DEX regardless.
- **Added `native_r8` variant**: Flutter release builds run R8 by default, native template doesn't.
- Smoke tests run on a **new dedicated AVD `pilot_b_api36`** (Pixel 7, android-36 google_apis_playstore,
  6 GB data), seeded with 3 dummy contacts ("Pilot Dummy 1–3") and a mock GPS fix (49.2606, -123.2460).
  John's `Medium_Phone_API_36.1` AVD was not used: its /data was 94 % full (installs failed with
  "not enough space") and it holds John's own apps and 544 contacts — nothing on it was modified
  except installing/uninstalling the pilot apps during a first attempt.
  Runtime permissions are pre-granted with `adb pm grant`, so permission dialogs are not exercised.

**Smoke test** (`pilotB_flutter/smoke_test.py`, emulator only, refuses to run on anything but the
`pilot_b_api36` emulator): 4 variants × 5 behaviours all produced the expected output
(raw: `results/pilotB/screens/smoke_results.json`, 20 screenshots).

**Surprises (inputs for B3/B4, not results yet)**
1. **R8 renames almost all classes in the default Flutter release DEX**, including plugin code
   (quick look: most classes have 2-segment names like `a/b`; only one `com.baseflow.geolocator`
   class kept its name). The plan's package-prefix attribution will not work on R8-shrunk APKs.
   For the test pair we can deobfuscate with the saved mapping files; for the corpus this needs a
   decision (see checkpoint notes).
2. **`path_provider_android` 2.3.1 has no Java/Kotlin code**: it calls Android APIs from Dart via
   `package:jni` (`libdartjni.so`). Its Android API use is therefore invisible to DEX call-site
   extraction by construction.
3. `flutter_contacts` 2.x uses namespace `co.quis.flutter_contacts` — not in the plan's plugin list;
   attribution rules must be built from the actual plugin namespaces, not a fixed list.
4. `flutter build apk --release` is not byte-reproducible (two builds of the same source differed);
   the native Gradle build is. Analysis always uses the APK whose SHA-256 is recorded.
5. Android 16 / targetSdk 36 enforces edge-to-edge; the first native build hid two buttons under the
   action bar (fixed with inset padding + NoActionBar theme).

## 2026-11-01 — Decision: attribution under R8 renaming (John chose Option 2)

- Every APK gets an `r8_renamed` flag from the share of DEX classes whose simple name and package
  segments are all 1–2 characters (threshold to be fixed in B3 *before* looking at the
  Flutter-vs-native results, and recorded here).
- Attribution categories: `app_own`, `plugin_framework`, `other_library`, `unattributable_renamed`.
  Name-based rules (`attribution_rules.yaml`) apply wherever a meaningful name survives.
- Corpus results are reported separately for renamed and not-renamed APKs, with counts.
- The test pair is analysed both by name and after de-obfuscation with the saved R8 mapping files,
  to show what `unattributable_renamed` actually contains.
- Extra metric that does not depend on attribution: the share of requested dangerous permissions with
  no supporting sensitive call site in app-own code.
- Option 3 (Flutter plugin-registrant reachability) deferred; revisit after B3 if most Flutter
  call sites end up unattributable.

## 2026-11-01 — B2: corpus collection

**Source snapshot** (`results/pilotB/fdroid_snapshot.json`): F-Droid `index-v2.json`
(repo timestamp 1793418664799 ms, 4,923 packages) + `fdroiddata` build recipes (GitLab archive of
`metadata/`), both downloaded 2026-11-01, SHA-256 recorded.

**Decisions / deviations**
- **Framework candidates come from F-Droid's build recipes, not from repo file listings.**
  GITHUB_TOKEN was not set, and the recipes are a stronger signal anyway: they describe how F-Droid
  built the exact APK it distributes (e.g. Flutter apps pull the `flutter` srclib), they cover
  GitHub/GitLab/Codeberg repos alike, and they catch apps whose `pubspec.yaml` is in a subdirectory.
  Rules (on the most recent build entry): any `flutter` token → flutter; else npm/node/yarn/pnpm/
  react-native → react_native; dotnet/xamarin/maui → xamarin_maui; cordova/capacitor/ionic →
  web_hybrid; godot/unity/buildozer/kivy/qt/qmake/gomobile → other_engine; else a `gradle` key → native.
  Result (`candidates.csv`): native 4,007, flutter 529, react_native 229, unknown 81,
  other_engine 73, web_hybrid 4. Conservative: native apps that merely use npm/node at build time
  are excluded from the native pool. Every sampled APK is re-checked from its contents (below).
- **ABI-aware version choice**: F-Droid publishes per-ABI split APKs under different versionCodes;
  the naive "highest versionCode" picked an x86_64-only APK for 199 of 529 Flutter apps. Now: the
  highest versionCode whose `nativecode` includes arm64-v8a or is empty. 526/529 Flutter and
  4,001/4,007 native candidates have such an APK.
- **Matching**: Flutter APKs are much larger (median 25.1 MB vs 5.1 MB), so native apps are NOT
  matched to Flutter sizes (that would select atypically large native apps). Instead: Flutter is
  stratified by Flutter size quartile (15 per quartile); native gets per-category quotas proportional
  to the Flutter pool's primary-category mix (largest remainder, 60 total), with native size
  quartiles interleaved inside each category. Random order: seed 42. Queue: `sample_queue.csv`,
  quotas: `sample_quotas.json`.
- Download proceeds down each stratum's queue until its quota of *confirmed* APKs is met;
  every skipped app goes to `excluded.csv` with a reason. SHA-256 is checked against the index.
- Framework confirmation (from APK contents): Flutter = `libapp.so` + `libflutter.so`;
  native = neither, and no `index.android.bundle` / `libhermes*` / `libreactnative*` / `libjsc*`
  (React Native) and no `assemblies/` / `libmonodroid*` / `libmonosgen*` (Xamarin/MAUI). The
  libhermes/libmono checks are additions to the plan's list.
- Estimated download 2.66 GB (≈3.06 GB with replacements) — under the 5 GB ask-first threshold.

**Result** (`results/pilotB/corpus.csv`, `excluded.csv`; raw APKs in `data/raw/fdroid/apks/`, gitignored)
- 60 Flutter + 60 native F-Droid APKs, 120 unique app IDs and SHA-256s, all hashes match the index.
  Download 2.11 GB (Flutter) + 0.56 GB (native) = 2.66 GB.
- Every stratum filled from the first apps in its queue: **0 exclusions** (no download failures, no
  hash mismatches, no framework mismatches). All 60 Flutter APKs contain `libapp.so` + `libflutter.so`;
  no native APK contains Flutter, React Native or Xamarin markers. So the recipe-based pre-classification
  agreed with APK contents on all 120 sampled apps. (`excluded.csv` therefore contains only a header;
  the script now always writes the header.)
- APK size (MB) median [IQR]: Flutter 25.0 [20.4–45.3], native 5.5 [2.6–10.4].
- 32 of 60 native APKs ship no native code at all; 28 ship `.so` files (various ABIs).
- Anti-features (F-Droid labels, kept, not excluded): 17 Flutter and 12 native apps carry at least one
  (most often NonFreeNet; also TetheredNet, Ads, NonFreeAssets, Tracking, NonFreeDep). Benign by
  F-Droid's review; recorded for possible sensitivity analysis.

## 2026-11-02 — B3: feature extraction

**`r8_renamed` threshold, fixed before extracting the corpus** (calibrated only on the 4 test APKs):
- A class counts as *renamed* if every package segment and its simple name (before any `$`) are 1–2
  characters of `[A-Za-z0-9_$]`. Test APKs: native 0.000, native_r8 0.953, flutter_default 0.837,
  flutter_obfuscated 0.837 of DEX classes renamed.
- **`r8_renamed = share of renamed classes ≥ 0.5`.** The flag is only for splitting results; call-site
  attribution uses the per-class rule (a renamed caller is `unattributable_renamed` in any APK).
  Sensitivity at 0.3 and 0.7 is reported alongside.

**Extractor** (`pilotB_flutter/02_extract_features.py`, rules in `pilotB_flutter/attribution_rules.yaml`)
- Sensitive sinks: framework methods in 11 categories (plan's 9 + camera, microphone, used only for
  the permission metric), static reads of `ContactsContract`/`CallLog`/`Telephony.Sms`/`CalendarContract`
  fields (bytecode scan: androguard keeps no xrefs for external fields), and `content://` URI strings.
  `Context` file methods (`getFilesDir`, …) match on any receiver class, because Kotlin invokes them
  on the app's own Activity subclass (`MainActivity;->getFilesDir`).
- **App-own prefixes**: applicationId, plus the Application class and launcher activities, each cut
  to 3 package segments, and only if the class is *defined in the APK's DEX*. Bug found on the test
  pair: Flutter's template sets `android:name="android.app.Application"`, which first made
  `android.app` an app-own prefix.
- **Plugin namespaces**: static list (`io.flutter`, `dev.fluttercommunity`, `com.baseflow`,
  `com.github.dart_lang`, `co.quis.flutter_contacts`) + per-APK packages of classes referenced by
  `GeneratedPluginRegistrant` (when not renamed). Deviation: the plan's pubspec.lock-based list
  would need source checkouts; the registrant is in every Flutter APK and lists exactly the plugins
  compiled in.
- **De-obfuscation of the test pair is per method, not per class.** R8 merges static methods from
  unrelated classes into one class (e.g. `F0.b` maps to gms `InstantApps` but holds
  `flutter_contacts` methods) and inlines across classes, so each obfuscated method maps to the set of
  original classes in its mapping frames; if their categories disagree it is labelled
  `mixed:<cats>` (in the test pair: Kotlin stdlib / androidx frames inlined into plugin code).
  Frames qualified with an already-renamed package (`a.MainActivity$$ExternalSyntheticApiModelOutline1`)
  are resolved by simple class name.
- R8 API outlining moves even native app-own calls into renamed synthetic classes: in `native_r8`,
  `LocationManager.getCurrentLocation` is called from `a.b`
  (= `MainActivity$$ExternalSyntheticApiModelOutline1`). Without the mapping that call site is
  `unattributable_renamed` in a *native* app too.
- `dex_code_bytes_*` = instruction bytes (2 × code units) of methods per attribution category; a
  proxy for "DEX bytes by class". `dex_bytes` = uncompressed size of all `classes*.dex`.
- libapp.so strings: the arm64-v8a `libapp.so`, printable ASCII runs ≥ 6 (`strings -n 6`).
  `blutter` not attempted in this pass (optional); string evidence answers the plan's questions.
- Test-pair string dumps (`results/pilotB/test_pair_strings/`) escape control characters: raw Kotlin
  metadata strings contain NUL bytes, which made `grep` treat a dump as binary and miss matches.

**B3 run** (`results/pilotB/features.csv`, `api_calls.parquet`, `strings.parquet`, log `extract.log`):
124 APKs (120 corpus + 4 test), 0 errors, ≤ 22 s per APK; 25,053 call-site rows, 9,520 string rows.
All 60 Flutter APKs have `libapp.so`; 59/60 have a `GeneratedPluginRegistrant` (exception:
`com.gonnaggstudio.oh_tai_gi`).
- **Surprise: the renamed-class share is not bimodal for Flutter.** Histogram (10 bins, 0–1):
  Flutter `[0 1 5 4 6 8 6 14 14 2]`, native `[34 5 2 2 1 0 2 2 5 7]`. Flutter's keep rules keep many
  `io.flutter.*` names, so R8-built Flutter APKs with a small DEX sit at 20–35 % renamed. The
  pre-set flag (≥ 0.5) marks 44/60 Flutter and 16/60 native APKs as `r8_renamed` (0.3: 54/19;
  0.7: 30/14). Threshold kept as fixed; the split is reported with this caveat. Per-call-site
  attribution does not depend on it.

**Rule fix after the test pair** (before any corpus comparison): network sinks now list
`getInputStream`/`getOutputStream`/`connect` on `URLConnection`, `HttpURLConnection` and
`HttpsURLConnection`. The non-R8 native build references `HttpURLConnection;->getOutputStream`; R8
rewrites it to `URLConnection;->getOutputStream`, so only R8 builds were matched. Corpus re-extracted
(124 APKs, 0 errors, 25,087 call rows).

## 2026-11-02 — B4 part 1: test-app pair (`pilotB_flutter/03_analyze.py part1`)
Outputs: `results/pilotB/test_pair_table.csv` / `.md`, `test_pair_summary.json`. Counts are
distinct (calling method, sink) pairs ("caller methods"), not instruction-level call sites.
Findings (all from the files above):
- In both Flutter builds, none of the four API-backed behaviours has an app-own caller, by name or
  after per-method de-obfuscation. B1/B2 sinks are in geolocator / flutter_contacts plugin code
  (plus inlined androidx/Kotlin frames); B3 has no DEX network sink at all (Dart `http` uses the
  engine's native sockets); B4's 11 file sinks belong to the Flutter loader and androidx
  profileinstaller (path_provider uses `package:jni`, no Java code).
- The native twin has app-own callers for B1–B4 (R8 build: B1 is only app-own after de-obfuscation,
  because of API outlining).
- B3–B5 strings (URL, file name, dummy key) are in DEX for native, only in `libapp.so` for Flutter;
  `--obfuscate` keeps all three literals.
- `--obfuscate` leaves the DEX byte-identical to the default build; `libapp.so` shrinks
  3,736,496 → 3,081,136 bytes, printable strings 10,746 → 5,037, Dart package paths 23 → 2;
  `package:pilot_flutter/` and the method names `_readLocation`/`_postJson`/`_showMaskedKey`
  disappear.
- DEX instruction bytes attributed app-own: Flutter 8 (the empty `MainActivity`) vs native 2,426
  (2,088 in the R8 build).
- All 3 requested dangerous permissions of the Flutter app lack an app-own call site; 0 of 3 for native.

## 2026-11-02 — B4 part 2: metric definitions (fixed before computing any Flutter-vs-native statistic)
Unit = APK (60 Flutter, 60 native). Tests: two-sided Mann-Whitney U (scipy), Cliff's delta
(positive = Flutter larger), medians + IQR; Holm correction over the primary tests. Every metric is
reported for all apps and separately for `r8_renamed` true / false (threshold 0.5; primary metric also
at 0.3 / 0.7).
1. **Call-site attribution** (primary: `share_app_own`): per APK, share of sensitive (calling method,
   sink) rows by attribution category. Computed over all 13 sink categories, and again over the
   behavioural ones only (excluding crypto, reflection, dynamic_loading). APKs with 0 rows excluded
   from the share and counted.
2. **Code location by bytes**: `dex_app_own_code_share` = app-own DEX instruction bytes / all DEX
   instruction bytes (both frameworks); Flutter only: `libapp_file_share` = libapp.so bytes /
   (libapp.so + DEX file bytes). libapp.so also contains Flutter-framework and package Dart code, so
   it is an upper bound on app-specific code.
3. **App URLs**: a URL host counts as *common* if it occurs (DEX or libapp.so) in ≥ 6 of the 120
   corpus APKs (5 %), e.g. github.com, schemas.android.com, api.flutter.dev; `localhost`,
   `example.com`/`www.example.com` and hostless URLs are also dropped. App URLs = remaining URLs from
   DEX ∪ libapp.so. Per APK: share of its app URLs present in DEX strings; "only in libapp.so" = has
   ≥ 1 app URL and none in DEX. Limitation: URLs from a Dart package used by < 6 apps count as app URLs.
4. **Drebin-style features**: distinct features per APK (`perm`, `hw`, `comp`, `intent`, `api`, `url`),
   counts by origin; `drebin_app_own_share` = app-own / all non-manifest features (manifest
   permissions and hardware features cannot be attributed).
5. **Dangerous permissions without an app-own call site**: share among requested dangerous permissions
   mapped to a sink category (APKs with ≥ 1 mapped permission).
Primary tests (Holm): 1 (all categories), 2 (`dex_app_own_code_share`), 3, 4, 5.

## 2026-11-02 — B4 part 2: corpus results, first run (SUPERSEDED by the re-run after part 3; numbers kept for the record)
Outputs: `results/pilotB/summary.json` (all numbers below), `per_app_metrics.csv`,
`fig_attribution_share.png`, `fig_code_share.png`. 60 Flutter vs 60 native; Mann-Whitney U two-sided,
δ = Cliff's delta (Flutter vs native), Holm over the 5 primary tests.
- **Call-site attribution**: median app-own share Flutter 0.000 [IQR 0.000–0.000] vs native 0.004
  [0.000–0.029]; p = 3.6e-08, Holm 7.2e-08, δ = −0.48. Apps with ≥ 1 app-own sensitive call site:
  Flutter 5/60, native 31/57 (3 native apps have no sensitive sinks at all). Behavioural sinks only
  (no crypto/reflection/dynamic loading): 0.000 vs 0.018, p = 1.5e-07, δ = −0.46.
  Holds in both strata (renamed: p = 0.0015, δ = −0.37; not renamed: p = 0.00034, δ = −0.56) and at
  thresholds 0.3 / 0.7.
- **Surprise: native apps' sensitive calls are also mostly library code.** Unshrunk native apps
  ship all of androidx, whose own code calls location/file/reflection APIs (e.g. `de.herk.kfza`:
  240 sink rows, 0 app-own; callers androidx.core, androidx.compose, kotlin.io…). So the app-own share
  is low in both groups; the difference is between "rarely" and "almost never".
  Flutter's 5 app-own cases are genuine platform-channel Kotlin/Java written by the app (e.g.
  `com.zaifears.locreminder.LocationWatchService` → `requestLocationUpdates`).
- **Code location**: app-own share of DEX instruction bytes 0.000 [0.000–0.001] vs 0.014 [0.006–0.046],
  p = 2.6e-16, Holm 1.0e-15, δ = −0.87 (median app-own bytes 8 vs 25,026). Flutter: median 82.2 %
  [79.0–88.3] of code-file bytes are in `libapp.so` (median 8.0 MB) vs DEX (median 1.9 MB).
- **App URLs** (43 common hosts excluded): Flutter apps with app URLs: 48/60, of which **42 have them
  only in libapp.so**; median share of app URLs present in DEX 0.000 [0.000–0.000] vs native 1.000
  (by construction native URLs can only come from DEX; the Flutter numbers are the result).
  p = 1.6e-19, δ = −0.98.
- **Drebin-style features**: the number of distinct features does not differ (48.5 vs 55,
  p = 0.59, δ = −0.06), but their origin does: app-own share of attributable features 0.083
  [0.055–0.119] vs 0.210 [0.124–0.382], p = 2.5e-11, Holm 7.6e-11, δ = −0.71; Flutter engine/plugin
  origin 0.234 [0.157–0.373] of features in Flutter apps.
- **Dangerous permissions without an app-own call site**: no difference — median 1.0 in both
  (Flutter 24/25 apps, native 13/17 apps lack an app-own site for every mapped dangerous permission;
  p = 0.065, Holm 0.065). Consistent with the library finding above; not a Flutter-specific result.

## 2026-11-02 — B4 part 3: jadx spot-check (`04_spotcheck_sample.py`, `results/pilotB/spotcheck_sample.csv`)
jadx 1.5.6 (Homebrew). Sample fixed before decompiling: seed 42; 5 Flutter (3 renamed, 2 not) +
5 native (2 renamed, 3 not) corpus APKs; 8 call rows per APK (≤ 2 per attribution category, rest
random) = 80 rows; plus all 14 app-own rows of Flutter apps (targeted check). Each row checked against
the decompiled calling method: is the sink there, and whose code is it (judged from package,
strings, referenced classes).
the CSV holds an evidence note per row for re-checking.
(First draw had a bug: pandas 3 `groupby().apply` dropped the attribution column; redrawn before any
verdict was recorded.)
- Sink present in the decompiled method: 93/94 (1 unverifiable: jadx failed on that method).
- **Named attributions correct: 58/61** (random Flutter 26/27, random native 18/20, targeted Flutter
  app-own 14/14); 8 ambiguous, 1 unknown origin. The 3 errors:
  1. `android.support.v4.media.session.b.O` (diktafon, Flutter): Flutter `GeneratedPluginsRegister`
     code that R8 *merged into a class that kept a library package name* → labelled other_library.
     Not fixable without mapping files; a limitation of name-based attribution under R8.
  2–3. `android.support.multidex.*` labelled app-own (bouncy, native): the app's Application class is
     the bundled `MultiDexApplication`, so its package became an app-own prefix (2 corpus apps).
- Ambiguous (8 rows, maze_squirrel): `org.metatrans.commons.*` is the developer's own library shared
  across their apps; labelled other_library. Left as is (like a plugin, it is not specific to this
  app's intent), reported as ambiguous.
- Renamed rows (25): a reader can identify the origin of 24 — 22 library (mostly androidx), 2 Flutter
  engine/plugin, **0 app-own**, 1 unknown. So, in this sample, `unattributable_renamed` is not hiding
  app code.
- Second defect found: R8 `-repackageclasses` puts renamed classes in the **default package** with
  3-char names (`qs0`, `go0`, `wh2`), which the 1–2-char rule missed (7 such rows were labelled
  other_library; their category happened to be right).

**Rule fixes after the spot-check** (both in `attribution_rules.yaml`; full B3 re-extraction, part 1
and part 2 re-run):
- default-package classes count as renamed;
- Application/launcher classes in `android.`, `androidx.`, `com.google.`, `kotlin(x).`, `java(x).`
  never create an app-own prefix.
Test-pair table unchanged. `r8_renamed` (threshold still 0.5) now marks 50/60 Flutter and 28/60 native.

**B4 part 2, corrected numbers** (`summary.json`; figures regenerated):
- Call-site attribution, app-own share: Flutter 0.000 [0.000–0.000] vs native 0.004 [0.000–0.021];
  p = 9.5e-08, Holm 1.9e-07, δ = −0.46. Apps with any app-own sensitive call site: Flutter 5/60,
  native 30/57. Behavioural sinks only: 0.000 vs 0.008, p = 4.0e-07, δ = −0.44.
  Renamed stratum (50 F / 28 N): p = 0.0014, δ = −0.31; not renamed (10 F / 32 N): p = 0.0011,
  δ = −0.66. Threshold 0.3: renamed p = 0.00066 (57/29), not renamed p = 0.054 (only 3 Flutter apps);
  0.7: p = 0.025 (37/25) and 8.0e-06 (23/35).
- App-own share of DEX instruction bytes: 0.000 [0.000–0.001] vs 0.014 [0.006–0.046]; p = 2.6e-16,
  Holm 1.0e-15, δ = −0.87; median app-own bytes 8 vs 24,587. Flutter: 82.2 % [79.0–88.3] of code-file
  bytes in libapp.so.
- App URLs: 42 of 48 Flutter apps with app URLs have them only in libapp.so; p = 1.6e-19, δ = −0.98.
- Drebin-style features: count 48.5 vs 55 (p = 0.59); app-own share 0.083 [0.055–0.119] vs 0.205
  [0.124–0.362], p = 3.0e-11, Holm 8.9e-11, δ = −0.70; engine/plugin share in Flutter 0.234.
- Dangerous permissions without app-own call site: median 1.0 vs 1.0, p = 0.065 (no difference).

## 2026-11-02 — REPORT.md, Pilot B section
Written from `summary.json`, `test_pair_summary.json`, `test_pair_table.csv`, `spotcheck_sample.csv`
and `corpus.csv`; every number cross-checked by script against those files. Pilot A section is a
placeholder. Still open for Pilot B: `make pilotB` entry point + README.md, public repo push.

## 2026-11-02 — Pilot B entry point
- `Makefile`: `make setup`, `make pilotB` (build test apps only if missing → download the committed
  sample → extract → analyse), plus `pilotB-testapps`, `pilotB-smoke`, `pilotB-resample`,
  `pilotB-spotcheck-sample`. `pilotB_flutter/build_testapps.sh` scripts the four test-app builds and
  rewrites `test_apks.csv`. `README.md` documents both, and what is / is not bit-reproducible.
- Verified: `make pilotB` exits 0 and reproduces `summary.json` exactly. The parquet files first
  differed byte-wise only in row order (parallel workers finish in any order); outputs are now
  assembled in job order, and two consecutive runs are byte-identical across all of `results/pilotB/`.
- Not verified here: `make pilotB-testapps` on a clean checkout (re-running it would replace the test
  APKs whose hashes the report uses; Flutter builds are not byte-reproducible).

## 2026-11-02 — Repository split (John's decision)
This repository now holds Pilot B only, as a focused link for the Rubin email. Pilot A will get its
own repository later (e.g. `agent-suppression-study`, for the Chen email). Removed the Pilot A
placeholder section from REPORT.md and README.md and the empty `pilotA_suppressions/` folder;
`common/http.py` will be copied into the Pilot A repo. Earlier log entries are kept as written.
Before the first commit of `flutter-dex-blindspot`: `.gradle/` and `local.properties` (machine-specific
Gradle cache and local SDK path) added to `.gitignore` and unstaged. A secret scan found one real
Google API key from a third-party corpus app (`com.gokadzev.musify.fdroid`) in `strings.parquet`;
provider-format key matches are now stored redacted (first 4 chars + SHA-256 prefix). No analysis uses
key values; `summary.json` and `test_pair_summary.json` are byte-identical after the re-run.
