# Pilot B — Novelty check (Step B0)

Date: 2026-11-01. Sources searched: web search (general + scholarly), Semantic Scholar Graph API
(search + GlassWing citations), DBLP/ACM/IEEE landing pages via search results. Google Scholar was
not queried directly (no API; scraping is against its ToS) — **John: please do one manual Google
Scholar pass on "Flutter" + "malware detection" and on GlassWing's "cited by" list before we send emails.**

Depth of reading is marked per paper: **[full]** = full text read, **[abstract]** = abstract only,
**[secondary]** = only third-party summaries / search snippets.

## Bottom line

No paper found measures **how much of a Flutter app's behaviour is visible to the DEX/manifest
features used by learning-based Android malware detectors, with attribution of those features to
app-own vs. plugin/framework code, validated on a controlled Flutter/native twin app**. Not a stop
condition. The closest work (COMPSAC 2026, below) compares *security-scanner scores* across
frameworks, not detector feature visibility.

## Close papers

| # | Paper | What it measured | How Pilot B differs |
|---|---|---|---|
| 1 | Tegegn & Rubin, *The Illusion of Success: Learning-Based Android Malware Detectors (Replicability Study)*, Proc. ACM SE 3(ISSTA), ISSTA142, 2026. DOI 10.1145/3832233 **[full]** | SLR of classification-based detectors + longitudinal re-evaluation of 6 tools (Drebin, RevealDroid, MamaDroid, MalScan, InterpretDL, DetectBERT) on AndroZoo/VirusShare 2011–2023; naïve package-name classifier (SIM). | Motivating paper. Its Table 2 lists feature sources for 25 tools: by my reading of the extracted PDF text, only **2 of 25 (RevealDroid, GNNDroid)** use native code; of the 6 evaluated tools only RevealDroid does (system-call counts from native files). Pilot B quantifies what that means for Flutter apps, whose logic lives in native `libapp.so`. *(Verify the 2/25 count against the rendered PDF table before quoting.)* |
| 2 | Zhang et al., *GlassWing: A Tailored Static Analysis Approach for Flutter Android Apps*, ASE 2025. DOI 10.1109/ASE63991.2025.00050 **[abstract]** | Recovers implicit Dart↔Java invocations; on 1,023 Flutter apps, +141% Jimple lines with Soot, ~3× more FlowDroid leaks. | Improves taint/call-graph analysis for Flutter. Does not evaluate ML-detector feature sets or app-own vs. plugin attribution. Pilot B is a measurement of the *gap* GlassWing addresses, from the detector side. |
| 3 | Sterling et al., *Unveiling Security Traits of Cross-Platform Android Applications: A Large-Scale Empirical Study*, COMPSAC 2026. DOI 10.1109/COMPSAC69091.2026.00382 **[abstract]** — the only paper citing GlassWing per Semantic Scholar (2026-11-01) | 1,000 Flutter / 1,000 React Native / 1,000 Kotlin apps; MobSF scores and FlowDroid findings; "modest differences", explicitly no framework-level vulnerability claims. | **Closest work.** Measures scanner output distributions, not what detector features can see, not attribution, no ground-truth twin. Should be cited and contrasted in the emails/report. Full text is paywalled; John may want to read it via library access. |
| 4 | Samhi et al., *JuCify: A Step Towards Android Code Unification for Enhanced Static Analysis*, ICSE 2022 **[abstract]** | Merges native (.so) and DEX call graphs; shows many Java methods called from native code are unreachable without it, in goodware and malware. | Generic JNI native code, not Flutter's AOT Dart snapshot. Supports the general premise; does not touch learning-based detector features. |
| 5 | *ReuNify / Demystifying React Native Android Apps for Static Analysis*, TOSEM 2024 (DOI 10.1145/3702977) **[secondary]** | Unifies React Native JS/Hermes bytecode into Jimple; reports 441 RN apps among 60,618 VirusShare malware. | Analogous blind-spot argument for React Native, not Flutter; no detector-feature measurement. |
| 6 | Zeier, *Identifying Frameworks in Android Applications using Binary Code Function Similarity*, TU Wien diploma thesis, 2024 (DOI 10.34726/hss.2024.117246) **[secondary]** | Surveys/compares cross-platform framework detectors; proposes OAT function-similarity features. | Framework *identification*, not feature visibility. Useful for our framework-confirmation step (B2). |
| 7 | Apvrille, *Android Flutter Malware*, Virus Bulletin 2024 (Fortinet) + Fortinet FluHorse write-up **[secondary]** | Practitioner reverse-engineering of Flutter malware; notes disassemblers lacked Dart AOT support. | Industry evidence for the premise; no systematic measurement. Cite as motivation only. |
| 8 | Lviv Polytechnic study, 6,165 apps with MobSF across frameworks (2024/25) **[secondary]** | MobSF findings per framework (Flutter manifest/permission weaknesses etc.). | Same scanner-score angle as #3, weaker venue. |

Tooling (not papers, relevant to B3): `blutter`, `AOTopsy` (claims Dart 2.10–3.12, no VM execution),
`flutterdec`. AOTopsy may be a better best-effort option than blutter for Dart 3.11 — to evaluate in B3.

## Correction to the plan's framing of the Rubin paper

The plan says recall "varies from 56% to 94% across subsets". What the paper actually reports
(AndroZoo, temporally split):
- Tool-averaged **malware accuracy (= recall)** per split ranges from **52.8% (S2014) to 94.0% (S2019)**
  (Table 5); 56.3% is the S2011 value, not the minimum.
- "all tools have less than 60% recall for S2014 split, while they achieve more than 91% for the S2019 split".
- Per-split average **F1** ranges **65.1% (S2011) to 93.5% (S2019)** (Table 6); abstract: F1 "from high 60 to low 90 percent".

Recommended phrasing for emails: *"…F1 ranging from about 65% to 94% across temporal splits of the
same AndroZoo data, and a package-name-only classifier performing comparably."*

## Positioning sentence (draft)

Prior work either improves static analysis of Flutter apps (GlassWing) or compares security-scanner
scores across frameworks (Sterling et al., 2026); Pilot B instead asks what the feature extractors
used by learning-based detectors — 23 of 25 of which, per Tegegn & Rubin, ignore native code —
can actually observe about a Flutter app's own behaviour, using a ground-truth twin app.
