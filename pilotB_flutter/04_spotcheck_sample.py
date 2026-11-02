"""B4 part 3: draw the jadx spot-check sample (seeded) and decompile the sampled APKs.

Sample: 5 Flutter + 5 native corpus APKs that have sensitive call rows. Flutter: 3 r8_renamed +
2 not renamed; native: 2 r8_renamed + 3 not renamed (both strata covered in each framework).
Per APK, 8 call rows: up to 2 per attribution category present, the rest at random.
Separately, every app-own row of every Flutter app (a targeted check of the positive cases).

Outputs: results/pilotB/spotcheck_sample.csv (verdict columns filled in by hand),
decompiled sources in cache/jadx/<apk_id>/ (not committed).

Usage: python pilotB_flutter/04_spotcheck_sample.py [--decompile]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "pilotB"
JADX_OUT = ROOT / "cache" / "jadx"
SEED = 42
ROWS_PER_APK = 8
PLAN = {("flutter", True): 3, ("flutter", False): 2, ("native", True): 2, ("native", False): 3}


def sample() -> pd.DataFrame:
    feats = pd.read_csv(OUT / "features.csv")
    feats = feats[(feats.group == "corpus") & (feats.n_call_rows > 0)]
    calls = pd.read_parquet(OUT / "api_calls.parquet").reset_index(names="row_id")
    picked = []
    for (fw, renamed), k in PLAN.items():
        pool = feats[(feats.framework == fw) & (feats.r8_renamed == renamed)].sort_values("apk_id")
        picked += list(pool.sample(k, random_state=SEED).apk_id)
    rows = []
    for i, apk in enumerate(picked):
        c = calls[calls.apk_id == apk]
        first = c.sample(frac=1, random_state=SEED + i).groupby("attribution").head(2)
        rest = c.drop(first.index)
        extra = rest.sample(min(ROWS_PER_APK - len(first), len(rest)), random_state=SEED + i)
        rows.append(pd.concat([first, extra]).assign(sample="random"))
    fl_apps = feats[feats.framework == "flutter"].apk_id
    rows.append(calls[calls.apk_id.isin(fl_apps) & (calls.attribution == "app_own")].assign(sample="flutter_app_own"))
    s = pd.concat(rows).drop_duplicates("row_id")
    s = s.merge(feats[["apk_id", "framework", "r8_renamed", "app_own_prefixes"]], on="apk_id")
    cols = ["sample", "row_id", "apk_id", "framework", "r8_renamed", "app_own_prefixes", "kind", "sink",
            "category", "caller_class", "caller_method", "attribution"]
    s = s[cols].assign(sink_present="", manual_origin="", agrees="", evidence="")
    return s


def decompile(apks: list[str]) -> None:
    corpus = pd.read_csv(OUT / "corpus.csv").set_index("app_id")
    for a in apks:
        dest = JADX_OUT / a
        if dest.exists():
            continue
        subprocess.run(["jadx", "--no-res", "--show-bad-code", "-j", "4", "-d", str(dest),
                        str(ROOT / corpus.loc[a, "path"])], capture_output=True)
        print("decompiled", a, flush=True)


if __name__ == "__main__":
    s = sample()
    out = OUT / "spotcheck_sample.csv"
    if out.exists():
        sys.exit(f"{out} exists (may hold verdicts); delete it to redraw")
    s.to_csv(out, index=False)
    print(s.groupby(["sample", "framework", "apk_id", "r8_renamed"]).size().to_string())
    print(s.groupby(["sample", "framework", "attribution"]).size().to_string())
    if "--decompile" in sys.argv:
        decompile(sorted(s.apk_id.unique()))
