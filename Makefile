# Entry points for the pilots. See README.md.
PY := .venv/bin/python
B := pilotB_flutter
R := results/pilotB

.PHONY: setup pilotB pilotB-corpus pilotB-features pilotB-analysis pilotB-resample \
        pilotB-testapps pilotB-smoke pilotB-spotcheck-sample

setup: .venv/bin/python
.venv/bin/python: requirements.txt
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt
	touch $@

# Full Pilot B from the committed sample (results/pilotB/sample_queue.csv):
# download the 120 APKs, extract features, run the analysis.
pilotB: setup $(B)/apks/native.apk pilotB-corpus pilotB-features pilotB-analysis

# Test APKs are not committed; build them if missing (needs Flutter + Android SDK).
$(B)/apks/native.apk:
	$(MAKE) pilotB-testapps

pilotB-testapps:
	bash $(B)/build_testapps.sh

pilotB-corpus:
	$(PY) $(B)/01_collect_corpus.py download

pilotB-features:
	$(PY) $(B)/02_extract_features.py --only-test
	$(PY) $(B)/02_extract_features.py --workers 4

pilotB-analysis:
	$(PY) $(B)/03_analyze.py part1 part2

# Re-draw the sample from a fresh F-Droid index (changes the corpus; not part of `pilotB`).
pilotB-resample:
	$(PY) $(B)/01_collect_corpus.py index classify sample

# Emulator-only smoke test of the test apps (needs the pilot_b_api36 AVD running).
pilotB-smoke:
	$(PY) $(B)/smoke_test.py

# Re-draw the jadx spot-check sample (refuses to overwrite recorded verdicts).
pilotB-spotcheck-sample:
	$(PY) $(B)/04_spotcheck_sample.py --decompile
