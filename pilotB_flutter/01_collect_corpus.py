"""Pilot B, step B2: collect a benign Flutter vs. native APK corpus from F-Droid.

Stages (run in order; each caches its inputs and writes its outputs under
data/ and results/pilotB/):

  index     download F-Droid index-v2.json and the fdroiddata build-recipe archive
  classify  label each app flutter / native / other-cross-platform from its
            F-Droid build recipe (the recipe that actually produced the APK)
  sample    seed-42 sample of ~60 flutter + ~60 native apps, matched by
            category and APK-size quartile
  download  download the latest APK of each sampled app (<=1 req/s to F-Droid)
  confirm   confirm the framework from APK contents; write corpus.csv and
            excluded.csv

Usage: python pilotB_flutter/01_collect_corpus.py <stage> [...]
"""
from __future__ import annotations

import json
import re
import sys
import tarfile
import time
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import http  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fdroid"
OUT = ROOT / "results" / "pilotB"
INDEX_URL = "https://f-droid.org/repo/index-v2.json"
RECIPES_URL = "https://gitlab.com/fdroid/fdroiddata/-/archive/master/fdroiddata-master.tar.gz?path=metadata"
SEED = 42

# Markers searched in the build recipe (srclibs, sudo, init, prebuild, build, output, ...).
FRAMEWORK_MARKERS = {
    "flutter": [r"\bflutter\b"],
    "react_native": [r"react-native", r"\bnpm\b", r"\byarn\b", r"\bnodejs\b", r"\bnode\b", r"\bpnpm\b"],
    "xamarin_maui": [r"\bdotnet\b", r"\bxamarin\b", r"\bmaui\b"],
    "web_hybrid": [r"\bcordova\b", r"\bcapacitor\b", r"\bionic\b"],
    "other_engine": [r"\bgodot\b", r"\bunity\b", r"\bbuildozer\b", r"\bkivy\b", r"\bqt\b", r"\bqmake\b", r"\bgomobile\b"],
}


def stage_index() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, url in [("index-v2.json", INDEX_URL), ("fdroiddata-metadata.tar.gz", RECIPES_URL)]:
        dest = RAW / name
        info = http.download(url, dest)
        info["url"] = url
        info["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(dest.stat().st_mtime))
        meta[name] = info
    index = json.loads((RAW / "index-v2.json").read_text())
    meta["index-v2.json"]["repo_timestamp_ms"] = index["repo"]["timestamp"]
    meta["index-v2.json"]["packages"] = len(index["packages"])
    (OUT / "fdroid_snapshot.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


def _load_recipes() -> dict[str, dict]:
    recipes = {}
    with tarfile.open(RAW / "fdroiddata-metadata.tar.gz") as tar:
        for m in tar.getmembers():
            p = Path(m.name)
            if m.isfile() and p.suffix == ".yml" and p.parent.name == "metadata":
                try:
                    recipes[p.stem] = yaml.safe_load(tar.extractfile(m).read()) or {}
                except yaml.YAMLError:
                    recipes[p.stem] = {"_yaml_error": True}
    return recipes


def _recipe_framework(recipe: dict) -> tuple[str, str]:
    """Return (label, evidence) from the most recent build entry of a recipe."""
    builds = recipe.get("Builds") or []
    if not builds:
        return "no_builds", ""
    latest = builds[-1]
    text = json.dumps(latest).lower()
    hits = {fw: pat for fw, pats in FRAMEWORK_MARKERS.items() for pat in pats if re.search(pat, text)}
    if "flutter" in hits:
        return "flutter", hits["flutter"]
    others = [fw for fw in hits if fw != "flutter"]
    if others:
        return others[0], ",".join(f"{fw}:{hits[fw]}" for fw in others)
    if "gradle" in latest:
        return "native", "gradle"
    return "unknown", ""


def _latest_version(pkg: dict) -> dict | None:
    """Latest APK that runs on arm64: arm64-v8a in nativecode, or no native code.

    F-Droid publishes per-ABI split APKs under different versionCodes, so the
    plain highest versionCode is often an x86_64-only build.
    """
    versions = [v for v in (pkg.get("versions") or {}).values()
                if not v["manifest"].get("nativecode") or "arm64-v8a" in v["manifest"]["nativecode"]]
    if not versions:
        return None
    return max(versions, key=lambda v: v["manifest"].get("versionCode", 0))


def stage_classify() -> None:
    index = json.loads((RAW / "index-v2.json").read_text())
    recipes = _load_recipes()
    rows = []
    for app_id, pkg in index["packages"].items():
        md = pkg.get("metadata", {})
        latest = _latest_version(pkg)
        label, evidence = _recipe_framework(recipes.get(app_id, {})) if app_id in recipes else ("no_recipe", "")
        name = md.get("name") or {}
        rows.append({
            "app_id": app_id,
            "name": name.get("en-US") or next(iter(name.values()), ""),
            "categories": ";".join(md.get("categories") or []),
            "source_code": md.get("sourceCode", ""),
            "recipe_framework": label,
            "recipe_evidence": evidence,
            "version_name": latest["manifest"].get("versionName") if latest else None,
            "version_code": latest["manifest"].get("versionCode") if latest else None,
            "apk_file": latest["file"]["name"] if latest else None,
            "apk_sha256_index": latest["file"].get("sha256") if latest else None,
            "apk_size": latest["file"].get("size") if latest else None,
            "nativecode": ";".join(latest["manifest"].get("nativecode") or []) if latest else "",
            "anti_features": ";".join(sorted((latest or {}).get("antiFeatures") or {})),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "candidates.csv", index=False)
    print(df["recipe_framework"].value_counts().to_string())


TARGET_PER_GROUP = 60
APK_BASE = "https://f-droid.org/repo"
APK_DIR = RAW / "apks"


def _primary_category(cats) -> str:
    return str(cats).split(";")[0] if isinstance(cats, str) and cats else "None"


def _quotas(weights: pd.Series, total: int) -> dict[str, int]:
    """Largest-remainder apportionment of `total` over `weights`."""
    raw = weights / weights.sum() * total
    q = raw.astype(int)
    for k in (raw - q).sort_values(ascending=False).index[: total - q.sum()]:
        q[k] += 1
    return {k: int(v) for k, v in q.items() if v > 0}


def stage_sample() -> None:
    """Write a randomised download queue with per-stratum quotas.

    Flutter: stratified by Flutter APK-size quartile (equal quotas).
    Native: category quotas proportional to the Flutter pool's primary-category
    mix; within a category, queue order interleaves native size quartiles.
    Apps are downloaded down each stratum's queue until its quota of
    framework-confirmed APKs is met, so exclusions are replaced automatically.
    """
    df = pd.read_csv(OUT / "candidates.csv")
    df = df[df.apk_file.notna() & df.recipe_framework.isin(["flutter", "native"])].copy()
    df["primary_category"] = df.categories.map(_primary_category)
    df["size_quartile"] = df.groupby("recipe_framework").apk_size.transform(
        lambda s: pd.qcut(s, 4, labels=["Q1", "Q2", "Q3", "Q4"]).astype(str))
    df["rand"] = df.sample(frac=1, random_state=SEED).reset_index().reset_index().set_index("index")["level_0"]

    fl = df[df.recipe_framework == "flutter"].copy()
    fl["stratum"] = "size:" + fl.size_quartile
    fl_quota = {f"size:Q{i}": TARGET_PER_GROUP // 4 for i in range(1, 5)}

    nat = df[df.recipe_framework == "native"].copy()
    nat["stratum"] = "cat:" + nat.primary_category
    cat_quota = _quotas(fl.primary_category.value_counts(), TARGET_PER_GROUP)
    nat_quota = {f"cat:{c}": q for c, q in cat_quota.items()}
    # interleave size quartiles inside each category: rank within (category, quartile), then by rank
    nat["qrank"] = nat.groupby(["primary_category", "size_quartile"]).rand.rank()
    nat = nat.sort_values(["qrank", "rand"])
    fl = fl.sort_values("rand")

    queue = pd.concat([fl, nat])
    queue["queue_rank"] = queue.groupby("stratum").cumcount()
    queue = queue[queue.stratum.isin(list(fl_quota) + list(nat_quota))]
    queue.to_csv(OUT / "sample_queue.csv", index=False)
    quotas = {"flutter": fl_quota, "native": nat_quota}
    (OUT / "sample_quotas.json").write_text(json.dumps(quotas, indent=2))

    # Download-size estimate: first `quota` apps of each stratum, +15% buffer for exclusions.
    est = 0
    for fw, qs in quotas.items():
        for stratum, q in qs.items():
            est += queue[(queue.recipe_framework == fw) & (queue.stratum == stratum)].head(q).apk_size.sum()
    print(json.dumps(quotas, indent=1))
    print(f"estimated download: {est / 1e9:.2f} GB (+~15% for replacements ≈ {est * 1.15 / 1e9:.2f} GB)")


def _confirm_framework(apk: Path) -> tuple[str, str]:
    """Framework from APK entries. Returns (label, evidence)."""
    import zipfile
    with zipfile.ZipFile(apk) as z:
        names = z.namelist()
    libs = {n.split("/")[-1] for n in names if n.startswith("lib/")}
    has = lambda f: f in libs  # noqa: E731
    if has("libapp.so") and has("libflutter.so"):
        return "flutter", "libapp.so+libflutter.so"
    if has("libflutter.so") or has("libapp.so"):
        return "flutter_partial", ",".join(sorted(f for f in libs if f in ("libapp.so", "libflutter.so")))
    rn = [n for n in names if n.endswith("index.android.bundle")] + \
         sorted(f for f in libs if f.startswith(("libreactnative", "libhermes", "libjsc")))
    if rn:
        return "react_native", rn[0]
    xm = [n for n in names if n.startswith("assemblies/")] + \
         sorted(f for f in libs if f.startswith(("libmonodroid", "libmonosgen", "libxamarin")))
    if xm:
        return "xamarin_maui", xm[0]
    return "native", ""


def stage_download() -> None:
    queue = pd.read_csv(OUT / "sample_queue.csv")
    quotas = json.loads((OUT / "sample_quotas.json").read_text())
    kept, excluded = [], []
    for fw, qs in quotas.items():
        for stratum, quota in qs.items():
            n_ok = 0
            for row in queue[(queue.recipe_framework == fw) & (queue.stratum == stratum)].itertuples():
                if n_ok >= quota:
                    break
                dest = APK_DIR / fw / row.apk_file.lstrip("/")
                try:
                    info = http.download(APK_BASE + row.apk_file, dest)
                except Exception as e:  # noqa: BLE001
                    excluded.append({**row._asdict(), "reason": f"download_failed: {e}"})
                    continue
                rec = {**row._asdict(), "path": str(dest.relative_to(ROOT)), "sha256": info["sha256"],
                       "bytes": info["bytes"],
                       "download_date": time.strftime("%Y-%m-%d", time.gmtime(dest.stat().st_mtime))}
                if row.apk_sha256_index and info["sha256"] != row.apk_sha256_index:
                    excluded.append({**rec, "reason": "sha256_mismatch_with_index"})
                    continue
                label, evidence = _confirm_framework(dest)
                rec.update(framework_confirmed=label, framework_evidence=evidence)
                if label != fw:
                    excluded.append({**rec, "reason": f"framework_mismatch: recipe={fw} apk={label} ({evidence})"})
                    continue
                kept.append(rec)
                n_ok += 1
            if n_ok < quota:
                print(f"[warn] {fw} {stratum}: only {n_ok}/{quota} confirmed (queue exhausted)")
            print(f"{fw:8s} {stratum:28s} {n_ok}/{quota}")
    cols = ["app_id", "name", "source", "version_name", "version_code", "primary_category", "categories",
            "recipe_framework", "framework_confirmed", "framework_evidence", "stratum", "size_quartile",
            "bytes", "sha256", "download_date", "path", "nativecode", "anti_features", "source_code"]
    corpus = pd.DataFrame(kept).assign(source="f-droid")
    corpus[cols].to_csv(OUT / "corpus.csv", index=False)
    pd.DataFrame(excluded, columns=["app_id", "name", "stratum", "recipe_framework", "reason"]).to_csv(
        OUT / "excluded.csv", index=False)
    print(corpus.groupby("framework_confirmed").agg(n=("app_id", "size"), gb=("bytes", lambda b: b.sum() / 1e9)))
    print(f"excluded: {len(excluded)}")


STAGES = {"index": stage_index, "classify": stage_classify, "sample": stage_sample,
          "download": stage_download}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for stage in sys.argv[1:] or ["index", "classify"]:
        print(f"== {stage}")
        STAGES[stage]()
