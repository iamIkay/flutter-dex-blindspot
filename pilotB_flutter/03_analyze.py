"""B4: analysis of the B3 features.

  part1  test-app pair: per ground-truth behaviour and build variant, is the behaviour visible in
         DEX features, to whom are its call sites attributed, and where do its strings live.
         -> results/pilotB/test_pair_table.csv, test_pair_table.md, test_pair_summary.json

Usage: python pilotB_flutter/03_analyze.py part1
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
OUT = ROOT / "results" / "pilotB"
VARIANTS = ["native", "native_r8", "flutter_default", "flutter_obfuscated"]
CATEGORY = {"B1_location": "location", "B2_contacts_count": "contacts",
            "B3_https_post": "network", "B4_private_file": "file", "B5_dummy_key": None}


def _strings(variant: str, source: str) -> str:
    p = OUT / "test_pair_strings" / f"{variant}_{source}.txt"
    return p.read_text() if p.exists() else ""


def _manifest_permissions(apk: Path) -> set[str]:
    from loguru import logger
    logger.remove()
    from androguard.core.apk import APK
    return set(APK(str(apk)).get_permissions())


def _dex_digest(apk: Path) -> str:
    with zipfile.ZipFile(apk) as z:
        h = hashlib.sha256()
        for n in sorted(x for x in z.namelist() if x.startswith("classes") and x.endswith(".dex")):
            h.update(z.read(n))
    return h.hexdigest()


def _counts(s: pd.Series) -> str:
    return "; ".join(f"{k}={v}" for k, v in s.value_counts().sort_index().items()) or "-"


def part1() -> None:
    gt = json.loads((HERE / "ground_truth.json").read_text())
    calls = pd.read_parquet(OUT / "api_calls_test.parquet")
    feats = pd.read_csv(OUT / "features_test.csv").set_index("apk_id")
    apks = pd.read_csv(OUT / "test_apks.csv").set_index("variant")
    rows = []
    for v in VARIANTS:
        apk = ROOT / apks.loc[v, "apk"]
        perms = _manifest_permissions(apk)
        dex, lib = _strings(v, "dex"), _strings(v, "libapp")
        for b in gt["behaviours"]:
            cat = CATEGORY[b["id"]]
            sites = calls[(calls.apk_id == v) & (calls.category == cat)] if cat else calls.iloc[0:0]
            has_map = sites["attribution_deobf"].notna().any()
            rows.append(dict(
                behaviour=b["id"], variant=v, sink_category=cat or "",
                permissions_declared=all(p in perms for p in b["permissions"]) if b["permissions"] else None,
                n_call_rows=len(sites),
                n_call_rows_app_own=int((sites.attribution == "app_own").sum()),
                attribution_by_name=_counts(sites.attribution),
                n_call_rows_app_own_deobf=int((sites.attribution_deobf == "app_own").sum()) if has_map else None,
                attribution_deobf=_counts(sites.attribution_deobf) if has_map else None,
                strings=";".join(b.get("strings", [])),
                strings_in_dex=all(s in dex for s in b["strings"]) if b.get("strings") else None,
                strings_in_libapp=all(s in lib for s in b["strings"]) if b.get("strings") else None,
            ))
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "test_pair_table.csv", index=False)

    # Extra facts the table refers to.
    lib = {v: _strings(v, "libapp") for v in VARIANTS}
    summary = {
        "dex_sha256": {v: _dex_digest(ROOT / apks.loc[v, "apk"]) for v in VARIANTS},
        "libapp_bytes": {v: int(feats.loc[v, "libapp_bytes"]) for v in VARIANTS},
        "dex_bytes": {v: int(feats.loc[v, "dex_bytes"]) for v in VARIANTS},
        "dex_code_bytes": {v: {k: int(feats.loc[v, f"dex_code_bytes_{k}"]) for k in
                               ["app_own", "plugin_framework", "other_library", "unattributable_renamed"]}
                           for v in VARIANTS},
        "share_renamed": {v: round(float(feats.loc[v, "share_renamed"]), 3) for v in VARIANTS},
        "n_libapp_strings": {v: int(feats.loc[v, "n_libapp_strings"]) for v in VARIANTS},
        "n_dart_packages": {v: int(feats.loc[v, "n_dart_packages"]) for v in VARIANTS},
        "libapp_has_app_dart_path": {v: "package:pilot_flutter/" in lib[v] for v in VARIANTS},
        "libapp_has_app_function_names": {v: {n: n in lib[v] for n in ["_readLocation", "_postJson", "_showMaskedKey"]}
                                          for v in VARIANTS},
        "dangerous_no_appown_site": {v: str(feats.loc[v, "dangerous_no_appown_site"]) for v in VARIANTS},
        "n_drebin": {v: {k: int(feats.loc[v, f"n_drebin_{k}"]) for k in
                         ["manifest", "app_own", "plugin_framework", "other_library", "unattributable_renamed", "unknown"]}
                     for v in VARIANTS},
    }
    summary["dex_identical_default_vs_obfuscated"] = (
        summary["dex_sha256"]["flutter_default"] == summary["dex_sha256"]["flutter_obfuscated"])
    (OUT / "test_pair_summary.json").write_text(json.dumps(summary, indent=2))

    # Human-readable 5 x variant table.
    def cell(r) -> str:
        parts = []
        if r.sink_category:
            own = f"{r.n_call_rows_app_own} app-own"
            if pd.notna(r.n_call_rows_app_own_deobf):
                own += f" ({int(r.n_call_rows_app_own_deobf)} after deobf)"
            parts.append(f"{r.n_call_rows} caller methods, {own}")
        if r.strings:
            where = [s for s, ok in [("DEX", r.strings_in_dex), ("libapp.so", r.strings_in_libapp)] if ok]
            parts.append("strings: " + ("+".join(where) if where else "none"))
        return "; ".join(parts)

    md = ["| behaviour | " + " | ".join(VARIANTS) + " |", "|---|" + "---|" * len(VARIANTS)]
    for b in gt["behaviours"]:
        sub = table[table.behaviour == b["id"]].set_index("variant")
        md.append(f"| {b['id']} | " + " | ".join(cell(sub.loc[v]) for v in VARIANTS) + " |")
    (OUT / "test_pair_table.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(json.dumps({k: summary[k] for k in ["dex_identical_default_vs_obfuscated", "libapp_bytes",
                                                "n_dart_packages", "libapp_has_app_dart_path",
                                                "libapp_has_app_function_names"]}, indent=1))


ORIGINS = ["app_own", "plugin_framework", "other_library", "unattributable_renamed"]
NON_BEHAVIOURAL = {"crypto", "reflection", "dynamic_loading"}
COMMON_HOST_MIN_APPS = 6  # 5 % of the 120 corpus APKs
DROP_HOSTS = {"", "localhost", "example.com", "www.example.com"}
STRATA = {"all": None, "renamed": True, "not_renamed": False}
PRIMARY = ["call_share_app_own", "dex_app_own_code_share", "app_url_share_in_dex",
           "drebin_app_own_share", "dangerous_no_appown_share"]


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def cliffs_delta(x, y) -> float:
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    return float(((x[:, None] > y[None, :]).sum() - (x[:, None] < y[None, :]).sum()) / (len(x) * len(y)))


def _describe(s: pd.Series) -> dict:
    s = s.dropna()
    return {"n": int(len(s)), "median": float(s.median()) if len(s) else None,
            "q1": float(s.quantile(.25)) if len(s) else None, "q3": float(s.quantile(.75)) if len(s) else None,
            "mean": float(s.mean()) if len(s) else None}


def _compare(df: pd.DataFrame, metric: str) -> dict:
    from scipy.stats import mannwhitneyu
    fl, na = df.loc[df.framework == "flutter", metric].dropna(), df.loc[df.framework == "native", metric].dropna()
    res = {"flutter": _describe(fl), "native": _describe(na)}
    if len(fl) >= 3 and len(na) >= 3:
        u = mannwhitneyu(fl, na, alternative="two-sided")
        res.update(U=float(u.statistic), p=float(u.pvalue), cliffs_delta=cliffs_delta(fl, na))
    return res


def per_app_metrics() -> pd.DataFrame:
    feats = pd.read_csv(OUT / "features.csv")
    feats = feats[feats.group == "corpus"].set_index("apk_id")
    calls = pd.read_parquet(OUT / "api_calls.parquet")
    calls = calls[calls.apk_id.isin(feats.index)]
    strs = pd.read_parquet(OUT / "strings.parquet")
    strs = strs[strs.apk_id.isin(feats.index) & (strs.kind == "url")].copy()

    m = feats[["framework", "share_renamed", "r8_renamed"]].copy()
    # 1. call-site attribution shares
    for name, sub in [("call", calls), ("bcall", calls[~calls.category.isin(NON_BEHAVIOURAL)])]:
        ct = pd.crosstab(sub.apk_id, sub.attribution).reindex(index=m.index, columns=ORIGINS, fill_value=0)
        tot = ct.sum(axis=1)
        m[f"{name}_rows"] = tot
        for o in ORIGINS:
            m[f"{name}_share_{o}"] = (ct[o] / tot).where(tot > 0)
    # 2. code location
    code = feats[[f"dex_code_bytes_{o}" for o in ORIGINS]]
    m["dex_code_bytes"] = code.sum(axis=1)
    m["dex_app_own_code_bytes"] = feats["dex_code_bytes_app_own"]
    m["dex_app_own_code_share"] = feats["dex_code_bytes_app_own"] / m["dex_code_bytes"]
    m["dex_bytes"], m["libapp_bytes"] = feats["dex_bytes"], feats["libapp_bytes"]
    m["libapp_file_share"] = (feats["libapp_bytes"] / (feats["libapp_bytes"] + feats["dex_bytes"])).where(
        feats.framework == "flutter")
    # 3. app URLs
    strs["host"] = strs.value.map(_host)
    host_apps = strs.drop_duplicates(["apk_id", "host"]).groupby("host").apk_id.nunique()
    common = set(host_apps[host_apps >= COMMON_HOST_MIN_APPS].index) | DROP_HOSTS
    app = strs[~strs.host.isin(common)]
    dex_vals = app[app.source == "dex"].groupby("apk_id").value.agg(set)
    all_vals = app.groupby("apk_id").value.agg(set)
    m["n_app_urls"] = all_vals.reindex(m.index).map(lambda s: len(s) if isinstance(s, set) else 0)
    m["n_app_urls_in_dex"] = [len(all_vals.get(a, set()) & dex_vals.get(a, set())) for a in m.index]
    m["app_url_share_in_dex"] = (m.n_app_urls_in_dex / m.n_app_urls).where(m.n_app_urls > 0)
    m["app_urls_only_in_libapp"] = (m.n_app_urls > 0) & (m.n_app_urls_in_dex == 0)
    # 4. Drebin-style features
    m["n_drebin"] = feats["n_drebin"]
    for o in ["manifest", *ORIGINS, "unknown"]:
        m[f"n_drebin_{o}"] = feats[f"n_drebin_{o}"]
    attributable = feats["n_drebin"] - feats["n_drebin_manifest"]
    m["drebin_app_own_share"] = (feats["n_drebin_app_own"] / attributable).where(attributable > 0)
    m["drebin_plugin_framework_share"] = (feats["n_drebin_plugin_framework"] / attributable).where(attributable > 0)
    # 5. dangerous permissions
    m["n_dangerous_mapped"] = feats["n_dangerous_mapped"]
    m["dangerous_no_appown_share"] = (feats["n_dangerous_no_appown_site"] / feats["n_dangerous_mapped"]).where(
        feats["n_dangerous_mapped"] > 0)
    m.attrs["common_hosts"] = sorted(h for h in common if h)
    return m


def part2() -> None:
    m = per_app_metrics()
    m.to_csv(OUT / "per_app_metrics.csv")
    metrics = (PRIMARY + [f"call_share_{o}" for o in ORIGINS[1:]] + [f"bcall_share_{o}" for o in ORIGINS] +
               ["dex_code_bytes", "dex_app_own_code_bytes", "dex_bytes", "libapp_bytes", "libapp_file_share",
                "n_app_urls", "n_drebin", "n_drebin_app_own", "n_drebin_plugin_framework",
                "n_drebin_other_library", "n_drebin_unattributable_renamed", "drebin_plugin_framework_share"])
    out: dict = {"n_apps": m.framework.value_counts().to_dict(), "strata": {}, "definitions": "see LOG.md, B4 part 2"}
    for sname, flag in STRATA.items():
        df = m if flag is None else m[m.r8_renamed == flag]
        out["strata"][sname] = {"n_apps": df.framework.value_counts().to_dict(),
                                "metrics": {k: _compare(df, k) for k in metrics}}
    # Holm over the primary tests in the "all" stratum.
    prim = [(k, out["strata"]["all"]["metrics"][k].get("p")) for k in PRIMARY]
    prim = sorted([(k, p) for k, p in prim if p is not None], key=lambda t: t[1])
    running = 0.0
    for i, (k, p) in enumerate(prim):
        running = max(running, min(1.0, p * (len(prim) - i)))
        out["strata"]["all"]["metrics"][k]["p_holm"] = running
    # Sensitivity of the primary metric to the r8_renamed threshold.
    out["threshold_sensitivity"] = {}
    for t in (0.3, 0.5, 0.7):
        for flag in (True, False):
            df = m[(m.share_renamed >= t) == flag]
            out["threshold_sensitivity"][f"{t}_{'renamed' if flag else 'not_renamed'}"] = {
                "n_apps": df.framework.value_counts().to_dict(), "call_share_app_own": _compare(df, "call_share_app_own")}
    # Counts the report quotes directly.
    fl, na = m[m.framework == "flutter"], m[m.framework == "native"]
    out["counts"] = {
        "apps_without_sensitive_calls": {"flutter": int((fl.call_rows == 0).sum()), "native": int((na.call_rows == 0).sum())},
        "apps_with_zero_app_own_calls": {"flutter": int((fl.call_share_app_own == 0).sum()),
                                         "native": int((na.call_share_app_own == 0).sum())},
        "apps_with_app_urls": {"flutter": int((fl.n_app_urls > 0).sum()), "native": int((na.n_app_urls > 0).sum())},
        "apps_app_urls_only_in_libapp": {"flutter": int(fl.app_urls_only_in_libapp.sum()),
                                         "native": int(na.app_urls_only_in_libapp.sum())},
        "apps_with_mapped_dangerous_perm": {"flutter": int((fl.n_dangerous_mapped > 0).sum()),
                                            "native": int((na.n_dangerous_mapped > 0).sum())},
        "apps_all_dangerous_without_appown_site": {"flutter": int((fl.dangerous_no_appown_share == 1).sum()),
                                                   "native": int((na.dangerous_no_appown_share == 1).sum())},
        "r8_renamed": {"flutter": int(fl.r8_renamed.sum()), "native": int(na.r8_renamed.sum())},
    }
    out["common_hosts"] = m.attrs["common_hosts"]
    (OUT / "summary.json").write_text(json.dumps(out, indent=2))
    figures(m)
    for k in PRIMARY:
        r = out["strata"]["all"]["metrics"][k]
        print(f"{k:28s} F {r['flutter']['median']:.3f} [{r['flutter']['q1']:.3f}-{r['flutter']['q3']:.3f}] n={r['flutter']['n']}"
              f" | N {r['native']['median']:.3f} [{r['native']['q1']:.3f}-{r['native']['q3']:.3f}] n={r['native']['n']}"
              f" | p={r.get('p', float('nan')):.2g} holm={r.get('p_holm', float('nan')):.2g} d={r.get('cliffs_delta', float('nan')):.2f}")
    print(json.dumps(out["counts"]))


# Chart styling (dataviz default palette, light surface).
SURFACE, INK, INK2, GRID = "#fcfcfb", "#1f1f1e", "#5f5e58", "#e6e5e0"
ORIGIN_COLORS = {"app_own": "#2a78d6", "plugin_framework": "#eb6834",
                 "other_library": "#1baf7a", "unattributable_renamed": "#eda100"}
ORIGIN_LABELS = {"app_own": "app-own", "plugin_framework": "Flutter engine / plugin",
                 "other_library": "other library", "unattributable_renamed": "renamed (unattributable)"}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def figures(m: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "text.color": INK, "axes.labelcolor": INK2})

    # Figure 1: per-app attribution of sensitive call sites, one 100 % bar per app.
    fig, axes = plt.subplots(1, 2, figsize=(10, 7.5), sharex=True, facecolor=SURFACE)
    for ax, fw in zip(axes, ["flutter", "native"]):
        d = m[(m.framework == fw) & (m.call_rows > 0)].sort_values(
            ["call_share_app_own", "call_share_plugin_framework"], ascending=True)
        left = pd.Series(0.0, index=d.index)
        for o in ORIGINS:
            w = d[f"call_share_{o}"]
            ax.barh(range(len(d)), w, left=left, height=0.8, color=ORIGIN_COLORS[o],
                    edgecolor=SURFACE, linewidth=0.6, label=ORIGIN_LABELS[o])
            left += w
        _style(ax)
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        n_own = int((d.call_share_app_own > 0).sum())
        ax.set_title(f"{fw.capitalize()}: {n_own} of {len(d)} apps have any app-own call site",
                     loc="left", fontsize=10, color=INK)
        ax.set_xlabel("share of sensitive API call sites (calling method × sink)")
    axes[0].set_ylabel("apps, sorted by app-own share")
    h, l = axes[0].get_legend_handles_labels()
    fig.suptitle("Who calls sensitive Android APIs in the DEX?", x=0.06, ha="left", y=0.985, fontsize=12)
    fig.legend(h, l, loc="upper left", bbox_to_anchor=(0.055, 0.955), ncol=4, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUT / "fig_attribution_share.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)

    # Figure 2: where Flutter apps' code bytes live, libapp.so vs DEX.
    d = m[m.framework == "flutter"].sort_values("libapp_file_share")
    fig, ax = plt.subplots(figsize=(8, 7.5), facecolor=SURFACE)
    lib_share = d.libapp_file_share
    ax.barh(range(len(d)), lib_share, height=0.8, color="#2a78d6", edgecolor=SURFACE, linewidth=0.6,
            label="libapp.so (Dart AOT snapshot)")
    ax.barh(range(len(d)), 1 - lib_share, left=lib_share, height=0.8, color="#eb6834", edgecolor=SURFACE,
            linewidth=0.6, label="classes*.dex (all DEX code)")
    _style(ax)
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_ylabel(f"Flutter apps (n={len(d)}), sorted")
    ax.set_xlabel("share of code-file bytes (uncompressed)")
    ax.set_title(f"Flutter apps: median {lib_share.median():.0%} of code bytes are in libapp.so; "
                 f"median app-own DEX code: {d.dex_app_own_code_bytes.median():,.0f} instruction bytes",
                 loc="left", fontsize=10, color=INK)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "fig_code_share.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


STAGES = {"part1": part1, "part2": part2}

if __name__ == "__main__":
    for stage in sys.argv[1:] or STAGES:
        STAGES[stage]()
