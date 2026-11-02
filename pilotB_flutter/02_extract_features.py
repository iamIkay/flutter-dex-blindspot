"""B3: static feature extraction for the test-app pair and the F-Droid corpus.

For each APK (androguard, static only): Drebin-style features (permissions,
sensitive framework API call sites, hardware features, components, intent
actions, DEX URLs), call-site attribution per attribution_rules.yaml, size
metrics, and strings from libapp.so (Flutter).

Outputs (results/pilotB/):
  features.csv          one row per APK
  api_calls.parquet     one row per (APK, sensitive sink, calling method)
  strings.parquet       URLs / key-like tokens / content URIs / Dart package paths
  test_pair_strings/    full DEX and libapp.so string dumps for the 4 test APKs

Per-APK results are cached in cache/features/ keyed by APK SHA-256 and the
hash of this script + rules, so reruns only redo what changed.

Usage: python pilotB_flutter/02_extract_features.py [--workers N] [--only-test]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
import sys
import time
import zipfile
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
OUT = ROOT / "results" / "pilotB"
CACHE = ROOT / "cache" / "features"
RULES_PATH = HERE / "attribution_rules.yaml"
RULES = yaml.safe_load(RULES_PATH.read_text())
CODE_VERSION = hashlib.sha256(Path(__file__).read_bytes() + RULES_PATH.read_bytes()).hexdigest()[:12]

SEG = re.compile(RULES["renamed"]["segment_regex"])
PLUGIN_STATIC = [p.rstrip(".") for p in RULES["plugin_framework"]["prefixes"]]
SGET_OPS = range(0x60, 0x67)  # sget, sget-wide, -object, -boolean, -byte, -char, -short
ORIGIN_ORDER = ["app_own", "plugin_framework", "other_library", "unattributable_renamed"]


def _sinks() -> tuple[dict, dict]:
    """method name -> [(class or '*', category, spec)]."""
    by_name: dict[str, list] = {}
    for cat, specs in RULES["sensitive_api"].items():
        for spec in specs:
            cls, meth = spec.split(";->")
            cls = "*" if cls == "*" else cls + ";"
            by_name.setdefault(meth, []).append((cls, cat, spec))
    return by_name, RULES["sensitive_fields"]


SINKS, FIELD_SINKS = _sinks()
URL_RE = re.compile(RULES["strings"]["url"])
PKG_RE = re.compile(RULES["strings"]["dart_package"])
KEY_RES = {k: re.compile(v) for k, v in RULES["strings"]["key_like"].items()}
CURI_RES = {k: re.compile(v) for k, v in RULES["content_uri_strings"].items()}
PRINTABLE = re.compile(rb"[\x20-\x7e]{%d,}" % RULES["strings"]["min_len"])


def dotted(name: str) -> str:
    return name[1:-1].replace("/", ".") if name.startswith("L") and name.endswith(";") else name


def is_renamed(name: str) -> bool:
    parts = dotted(name).split(".")
    if len(parts) == 1:  # default package: only R8-repackaged classes live there
        return True
    return all(SEG.match(s) for s in parts[:-1] + [parts[-1].split("$")[0] or parts[-1]])


def under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def own_prefix(pkg: str) -> str:
    return ".".join(pkg.split(".")[: RULES["app_own"]["max_segments"]])


class Attributor:
    def __init__(self, app_own: list[str], plugins: list[str]):
        self.app_own, self.plugins = app_own, plugins

    def __call__(self, cls: str) -> str:
        """Category of a class given as Dalvik (`La/b;`) or dotted name."""
        name = dotted(cls)
        if is_renamed(name):
            return "unattributable_renamed"
        if any(under(name, p) for p in self.app_own):
            return "app_own"
        if any(under(name, p) for p in self.plugins):
            return "plugin_framework"
        return "other_library"


MAP_METHOD = re.compile(r"^\s+(?:\d+:\d+:)?\S+ ([\w$.<>-]+)\(.*\)(?::\d+(?::\d+)?)? -> (\S+)$")


def load_mapping(path: Path) -> dict[str, tuple[str, dict[str, set[str]]]]:
    """R8 mapping.txt: obfuscated class -> (original class, {obfuscated method: original classes}).

    R8 merges and inlines code across classes, so one obfuscated method can carry frames
    from several original classes; all of them are kept.
    """
    m: dict = {}
    cur = None
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            orig, obf = line.rstrip(":").split(" -> ")
            cur = m[obf] = (orig, {})
        elif cur and (hit := MAP_METHOD.match(line)):
            name, obf_m = hit.groups()
            cls = name.rsplit(".", 1)[0] if "." in name else cur[0]
            cur[1].setdefault(obf_m, set()).add(cls)
    # Frames are sometimes qualified with an already-renamed package (`a.MainActivity$$...`);
    # resolve those by simple class name, preferring the enclosing class.
    by_simple: dict[str, set[str]] = {}
    for orig, _ in m.values():
        by_simple.setdefault(orig.rsplit(".", 1)[-1], set()).add(orig)
    for orig, methods in m.values():
        for k, classes in methods.items():
            fixed = set()
            for c in classes:
                pkg, _, simple = c.rpartition(".")
                if pkg and all(SEG.match(x) for x in pkg.split(".")) and simple in by_simple:
                    same = orig.rsplit(".", 1)[-1] == simple
                    fixed |= {orig} if same else by_simple[simple]
                else:
                    fixed.add(c)
            methods[k] = fixed
    return m


def merge_origin(origins: set[str]) -> str:
    """Origin of a feature seen at several sites: app_own wins, then plugin, library, renamed."""
    for o in ORIGIN_ORDER:
        if o in origins:
            return o
    return "unknown"


def libapp_strings(z: zipfile.ZipFile) -> tuple[str | None, list[str]]:
    names = [n for n in z.namelist() if n.endswith("/libapp.so")]
    pick = next((n for n in names if "/arm64-v8a/" in n), names[0] if names else None)
    if not pick:
        return None, []
    return pick, [s.decode() for s in PRINTABLE.findall(z.read(pick))]


def redact(token: str) -> str:
    """Provider-format credentials found in third-party APKs are not republished verbatim."""
    return f"{token[:4]}…sha256:{hashlib.sha256(token.encode()).hexdigest()[:12]}"


def string_hits(value: str) -> list[tuple[str, str]]:
    hits = [("url", u) for u in URL_RE.findall(value)]
    hits += [(f"key:{k}", m.group(0) if k == "named_key" else redact(m.group(0)))
             for k, r in KEY_RES.items() for m in r.finditer(value)]
    hits += [(f"content_uri:{k}", value) for k, r in CURI_RES.items() if r.search(value)]
    return hits


def analyze(job: dict) -> tuple[dict, list[dict], list[dict]]:
    from loguru import logger
    logger.remove()
    from androguard.misc import AnalyzeAPK

    t0 = time.time()
    apk_id, path = job["apk_id"], ROOT / job["path"]
    a, _, dx = AnalyzeAPK(str(path))
    mapping = load_mapping(ROOT / job["mapping"]) if job.get("mapping") else None
    pkg = a.get_package()
    internal = [c for c in dx.get_classes() if not c.is_external()]
    n_renamed = sum(is_renamed(c.name) for c in internal)

    # Plugin namespaces: static list + packages of classes the registrant references.
    registrant = dx.get_class_analysis(RULES["plugin_framework"]["registrant_class"])
    reg_plugins = sorted({
        ".".join(dotted(c.name).split(".")[:-1]) for c in (registrant.get_xref_to() if registrant else [])
        if not c.is_external() and not is_renamed(c.name)
    } - {""})

    # App-own prefixes: applicationId, Application class, launcher activities (unless framework/plugin).
    pre = Attributor([], PLUGIN_STATIC + reg_plugins)
    # Components count only if defined in this APK's DEX (not e.g. android.app.Application).
    defined = {dotted(c.name) for c in internal}
    lib_ns = tuple(RULES["app_own"]["exclude_prefixes"])
    comps = [pkg] + [x for x in [a.get_attribute_value("application", "name"), *a.get_main_activities()]
                     if x and x in defined and not x.startswith(lib_ns)]
    app_own = sorted({own_prefix(c if c == pkg else c.rsplit(".", 1)[0])
                      for c in comps if c == pkg or pre(c) == "other_library"})
    plugins = sorted(set(PLUGIN_STATIC + reg_plugins) - set(app_own))
    attr = Attributor(app_own, plugins)

    def attribute(cls: str, meth: str = "") -> tuple[str, str | None, str | None]:
        """(attribution, original classes, attribution after deobfuscation; 'mixed:...' if frames disagree)."""
        if mapping is None:
            return attr(cls), None, None
        orig_cls, methods = mapping.get(dotted(cls), (dotted(cls), {}))
        origs = methods.get(meth) or {orig_cls}
        cats = sorted({attr(o) for o in origs})
        return attr(cls), ";".join(sorted(origs)), cats[0] if len(cats) == 1 else "mixed:" + "+".join(cats)

    calls: list[dict] = []

    def add_call(kind, spec, cat, caller_cls, caller_meth, n_sites):
        cat_attr, orig, orig_attr = attribute(caller_cls, caller_meth)
        calls.append(dict(apk_id=apk_id, kind=kind, sink=spec, category=cat, caller_class=dotted(caller_cls),
                          caller_method=caller_meth, n_sites=n_sites, attribution=cat_attr,
                          caller_class_deobf=orig, attribution_deobf=orig_attr))

    # Sensitive framework method calls.
    for m in dx.get_methods():
        if not m.is_external() or m.name not in SINKS:
            continue
        for cls, cat, spec in SINKS[m.name]:
            if cls != "*" and cls != m.class_name:
                continue
            sites: dict[tuple, int] = {}
            for caller_ca, caller_m, _ in m.get_xref_from():
                k = (caller_ca.name, caller_m.name)
                sites[k] = sites.get(k, 0) + 1
            for (cc, cm), n in sites.items():
                add_call("method", spec if cls != "*" else f"{m.class_name}->{m.name}", cat, cc, cm, n)

    # One pass over internal code: code bytes per category and static reads of sensitive fields.
    code_bytes = dict.fromkeys(ORIGIN_ORDER, 0)
    field_sites: dict[tuple, int] = {}
    for m in dx.get_methods():
        if m.is_external():
            continue
        em = m.get_method()
        code = em.get_code()
        if code is None:
            continue
        code_bytes[attr(m.class_name)] += code.get_insns_size() * 2
        for ins in em.get_instructions():
            if ins.get_op_value() in SGET_OPS:
                ref = ins.get_translated_kind()
                for cat, prefixes in FIELD_SINKS.items():
                    if any(ref.startswith(p) for p in prefixes):
                        k = (cat, ref.split(" ")[0], m.class_name, m.name)
                        field_sites[k] = field_sites.get(k, 0) + 1
    for (cat, ref, cc, cm), n in field_sites.items():
        add_call("field", ref, cat, cc, cm, n)

    # DEX strings: URLs, key-like tokens, content URIs, attributed by referencing class.
    strings: list[dict] = []
    for s in dx.get_strings():
        v = s.get_value()
        hits = string_hits(v)
        if not hits:
            continue
        callers = {(c.name, mm.name) for c, mm in s.get_xref_from()}
        origins = {attr(c) for c, _ in callers}
        origins_deobf = {attribute(c, mm)[2] for c, mm in callers} if mapping else set()
        for kind, val in hits:
            strings.append(dict(apk_id=apk_id, source="dex", kind=kind, value=val[:500],
                                origin=merge_origin(origins), origin_deobf=";".join(sorted(origins_deobf)) if mapping else None))
            if kind.startswith("content_uri:"):
                for c, mm in callers:
                    add_call("content_uri", val[:200], kind.split(":")[1], c, mm, 1)

    # libapp.so strings (Flutter).
    z = zipfile.ZipFile(path)
    libapp_name, lstrs = libapp_strings(z)
    dart_pkgs = sorted({PKG_RE.match(x).group(0)[8:-1] for x in lstrs if PKG_RE.match(x)})
    seen = set()
    for x in lstrs:
        for kind, val in string_hits(x):
            if (kind, val) not in seen:
                seen.add((kind, val))
                strings.append(dict(apk_id=apk_id, source="libapp", kind=kind, value=val[:500], origin=None, origin_deobf=None))
    for p in dart_pkgs:
        strings.append(dict(apk_id=apk_id, source="libapp", kind="dart_package", value=p, origin=None, origin_deobf=None))
    if job.get("dump_strings"):
        d = OUT / "test_pair_strings"
        d.mkdir(parents=True, exist_ok=True)
        esc = lambda v: re.sub(r"[\x00-\x1f\x7f]", lambda c: f"\\x{ord(c.group()):02x}", v)  # grep-safe
        (d / f"{apk_id}_dex.txt").write_text("\n".join(sorted({esc(s.get_value()) for s in dx.get_strings()})))
        (d / f"{apk_id}_libapp.txt").write_text("\n".join(lstrs))

    # Drebin-style feature set with origins.
    feats: dict[str, set] = {}

    def feat(name, origin):
        feats.setdefault(name, set()).add(origin)

    for p in a.get_permissions():
        feat(f"perm::{p}", "manifest")
    for f in a.get_features():
        feat(f"hw::{f}", "manifest")
    for kind, names in [("activity", a.get_activities()), ("service", a.get_services()),
                        ("receiver", a.get_receivers()), ("provider", a.get_providers())]:
        for n in names:
            o = attr(n)
            feat(f"comp::{kind}::{n}", o)
            if kind != "provider":
                for act in (a.get_intent_filters(kind, n) or {}).get("action", []):
                    feat(f"intent::{act}", o)
    for c in calls:
        feat(f"api::{c['sink']}", c["attribution"])
    for s in strings:
        if s["source"] == "dex" and s["kind"] == "url":
            feat(f"url::{s['value']}", s["origin"])
    feat_origin = {k: merge_origin(v) if v != {"manifest"} else "manifest" for k, v in feats.items()}

    # Dangerous permissions without an app-own call site.
    perm_details = a.get_details_permissions()
    dangerous = sorted(p for p, d in perm_details.items() if d and "dangerous" in str(d[0]))
    pmap = RULES["permission_categories"]
    cats_any = {c["category"] for c in calls}
    cats_own = {c["category"] for c in calls if c["attribution"] == "app_own"}
    mapped = [p for p in dangerous if p in pmap]
    no_own = [p for p in mapped if not set(pmap[p]) & cats_own]
    no_any = [p for p in mapped if not set(pmap[p]) & cats_any]

    lib_arm64 = [i for i in z.infolist() if "/arm64-v8a/" in i.filename and i.filename.endswith(".so")]
    dex_infos = [i for i in z.infolist() if re.fullmatch(r"classes\d*\.dex", i.filename)]
    call_attr = pd.Series([c["attribution"] for c in calls], dtype=object).value_counts()
    origin_counts = pd.Series(list(feat_origin.values()), dtype=object).value_counts()
    row = dict(
        apk_id=apk_id, group=job["group"], framework=job["framework"], package=pkg,
        min_sdk=a.get_min_sdk_version(), target_sdk=a.get_target_sdk_version(),
        app_own_prefixes=";".join(app_own), registrant_plugins=";".join(reg_plugins),
        has_registrant=registrant is not None,
        n_classes=len(internal), n_classes_renamed=n_renamed, share_renamed=n_renamed / max(len(internal), 1),
        r8_renamed=n_renamed / max(len(internal), 1) >= RULES["renamed"]["apk_threshold"],
        n_dex=len(dex_infos), dex_bytes=sum(i.file_size for i in dex_infos),
        **{f"dex_code_bytes_{k}": v for k, v in code_bytes.items()},
        libapp_bytes=next((i.file_size for i in z.infolist() if i.filename == libapp_name), 0) if libapp_name else 0,
        libapp_path=libapp_name,
        libflutter_bytes=sum(i.file_size for i in lib_arm64 if i.filename.endswith("/libflutter.so")),
        native_lib_bytes_arm64=sum(i.file_size for i in lib_arm64),
        n_libapp_strings=len(lstrs), n_dart_packages=len(dart_pkgs), dart_packages=";".join(dart_pkgs),
        n_permissions=len(a.get_permissions()), n_dangerous=len(dangerous), n_dangerous_mapped=len(mapped),
        dangerous_mapped=";".join(mapped), dangerous_no_appown_site=";".join(no_own),
        n_dangerous_no_appown_site=len(no_own), n_dangerous_no_site=len(no_any),
        n_call_rows=len(calls), n_call_sites=sum(c["n_sites"] for c in calls),
        **{f"n_call_rows_{k}": int(call_attr.get(k, 0)) for k in ORIGIN_ORDER},
        n_dex_urls=sum(1 for s in strings if s["source"] == "dex" and s["kind"] == "url"),
        n_libapp_urls=sum(1 for s in strings if s["source"] == "libapp" and s["kind"] == "url"),
        n_drebin=len(feat_origin),
        **{f"n_drebin_{k}": int(origin_counts.get(k, 0)) for k in ["manifest", *ORIGIN_ORDER, "unknown"]},
        **{f"n_drebin_{p}": sum(1 for k in feat_origin if k.startswith(p + "::")) for p in
           ["perm", "hw", "comp", "intent", "api", "url"]},
        apk_sha256=job["sha256"], seconds=round(time.time() - t0, 1), code_version=CODE_VERSION,
    )
    return row, calls, strings


def cached_analyze(job: dict):
    f = CACHE / f"{job['sha256']}_{job['apk_id']}_{CODE_VERSION}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    try:
        res = analyze(job)
    except Exception as e:  # recorded, never silently dropped
        res = ({"apk_id": job["apk_id"], "group": job["group"], "framework": job["framework"],
                "error": f"{type(e).__name__}: {e}", "code_version": CODE_VERSION}, [], [])
    f.write_bytes(pickle.dumps(res))
    return res


def jobs(only_test: bool) -> list[dict]:
    test = pd.read_csv(OUT / "test_apks.csv")
    out = []
    for r in test.itertuples():
        out.append(dict(apk_id=r.variant, path=r.apk, sha256=r.sha256, group="test",
                        framework="flutter" if r.variant.startswith("flutter") else "native",
                        mapping=_mapping_for(r.variant), dump_strings=True))
    if not only_test:
        corpus = pd.read_csv(OUT / "corpus.csv")
        for r in corpus.itertuples():
            out.append(dict(apk_id=r.app_id, path=r.path, sha256=r.sha256, group="corpus",
                            framework=r.framework_confirmed))
    return out


def _mapping_for(variant: str) -> str | None:
    p = HERE / "mappings" / f"{variant}.mapping.txt"
    return str(p.relative_to(ROOT)) if p.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only-test", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = jobs(args.only_test)
    results = {}
    with Pool(args.workers, maxtasksperchild=4) as pool:
        for i, res in enumerate(pool.imap_unordered(cached_analyze, todo), 1):
            row = res[0]
            results[row["apk_id"]] = res
            print(f"[{i}/{len(todo)}] {row['apk_id']} {row.get('seconds', '')}s {row.get('error', '')}", flush=True)
    # Assemble in job order so outputs are byte-stable regardless of worker timing.
    ordered = [results[j["apk_id"]] for j in todo]
    feats = pd.DataFrame([r for r, _, _ in ordered])
    calls = [c for _, cs, _ in ordered for c in cs]
    strs = [x for _, _, ss in ordered for x in ss]
    suffix = "_test" if args.only_test else ""
    feats.to_csv(OUT / f"features{suffix}.csv", index=False)
    pd.DataFrame(calls).to_parquet(OUT / f"api_calls{suffix}.parquet", index=False)
    pd.DataFrame(strs).to_parquet(OUT / f"strings{suffix}.parquet", index=False)
    n_err = feats["error"].notna().sum() if "error" in feats else 0
    print(f"wrote {len(feats)} rows ({n_err} errors), {len(calls)} call rows, {len(strs)} string rows")


if __name__ == "__main__":
    sys.exit(main())
