# The Flutter blind spot in DEX-based Android malware detection (pilot)

How much of a Flutter app's behaviour is invisible to the DEX-based features used by Android malware
detectors? A small, reproducible pilot on a ground-truth test-app pair and 60 + 60 benign F-Droid
apps (code in `pilotB_flutter/`; "Pilot B" in the scripts and log).

The findings are in [REPORT.md](REPORT.md), and every decision, exclusion and surprise is in
[LOG.md](LOG.md).

## Requirements

- macOS or Linux with Python 3.13. Dependencies are pinned in `requirements.txt` (androguard 4.1.4,
  pandas, scipy, matplotlib, …).
- Only needed to rebuild the test apps:
  - Flutter 3.41.2 (Dart 3.11.0);
  - Android SDK 36;
  - JDK 17+ (Android Studio's JBR 21 was used).
  The full build environment is in `pilotB_flutter/ground_truth.json` → `build`.
- Optional:
  - jadx 1.5.6, for the spot-check;
  - an Android emulator, for the smoke test.
- Network access to `f-droid.org`. Downloads are throttled to 1 request/s and cached in `cache/`.
- About 3 GB of free disk for the corpus APKs (`data/raw/fdroid/apks/`).

No token or other secret is needed. (`common/http.py` would send a `GITHUB_TOKEN` from the
environment to api.github.com only; this pilot makes no GitHub API calls. Never commit `.env`.)

## Reproduce Pilot B

```bash
make setup
```

```bash
make pilotB
```

`make pilotB` runs these steps:

1. **Test apps.** It builds the four test-app variants with `pilotB_flutter/build_testapps.sh`, if
   `pilotB_flutter/apks/` is empty.
2. **Corpus.** It downloads the 120 sampled APKs listed in `results/pilotB/sample_queue.csv` and checks
   each SHA-256 against the F-Droid index. It writes `corpus.csv` and `excluded.csv`.
3. **Features.** It extracts features for the 4 test APKs and the 120 corpus APKs. It writes
   `features.csv`, `api_calls.parquet` and `strings.parquet`. Results are cached per APK in
   `cache/features/`.
4. **Analysis.** It writes the test-pair table (`test_pair_table.md`/`.csv`, `test_pair_summary.json`)
   and the corpus statistics (`summary.json`, `per_app_metrics.csv`, `fig_*.png`).

The run takes a few minutes plus the download; feature extraction takes about 3 minutes with 4 workers.
Every output goes to `results/pilotB/`.

Other targets:

| Target | What it does |
|---|---|
| `make pilotB-testapps` | Rebuild the four test APKs and their R8/Dart mapping files, and rewrite `results/pilotB/test_apks.csv`. |
| `make pilotB-smoke` | Run the 4 × 5 behaviour smoke test. It refuses to run on anything except an emulator running the `pilot_b_api36` AVD. |
| `make pilotB-resample` | Download a fresh F-Droid index and re-draw the sample. **This changes the corpus.** |
| `make pilotB-spotcheck-sample` | Re-draw and decompile the jadx spot-check sample. It refuses to overwrite `spotcheck_sample.csv`, which holds the recorded verdicts. |

### What is and is not bit-for-bit reproducible

- **The sample is fixed** by the committed `sample_queue.csv` and `sample_quotas.json` (seed 42). The
  F-Droid index it was drawn from is recorded by SHA-256 in `results/pilotB/fdroid_snapshot.json`.
  - A newer index gives a different sample, so `make pilotB` never re-samples.
  - If F-Droid stops serving one of the sampled APK versions, the download step skips to the next app
    in that stratum's queue and records the reason in `excluded.csv`.
- **The corpus APKs are identical** if they download, because each is checked against its recorded
  SHA-256.
- **The test APKs are not committed** (`*.apk` is gitignored) and **Flutter release builds are not
  byte-reproducible**. A rebuild gives new SHA-256s; R8 class names and some byte counts may differ
  slightly. The results in REPORT.md use the APKs whose hashes are in `results/pilotB/test_apks.csv`.
- **The spot-check verdicts** in `results/pilotB/spotcheck_sample.csv` were recorded by hand from jadx
  output. Each row has an evidence note.

## Layout

```
common/http.py              cached, throttled HTTP client (all downloads go through it)
pilotB_flutter/
  00_novelty_check.md       B0: related work
  testapp_flutter/          B1: Flutter test app (pubspec.lock pinned)
  testapp_native/           B1: native Kotlin twin
  ground_truth.json         B1: the five behaviours, expected APIs/strings, build versions
  build_testapps.sh         B1: build the 4 variants
  smoke_test.py             B1: emulator smoke test
  01_collect_corpus.py      B2: index -> classify -> sample -> download
  attribution_rules.yaml    B3: sinks, attribution and renaming rules
  02_extract_features.py    B3: androguard feature extraction
  03_analyze.py             B4: part1 (test pair), part2 (corpus statistics + figures)
  04_spotcheck_sample.py    B4: part3 (jadx spot-check sample)
results/pilotB/             every number in REPORT.md comes from a file here
LOG.md                      running log of decisions, exclusions and surprises
REPORT.md                   final write-up
```

## Safety

- Pilot B is static analysis of benign apps only: unzip, androguard and string extraction.
- No downloaded APK is ever installed on a device.
- Only the self-built test apps are installed, and only on a dedicated emulator.
