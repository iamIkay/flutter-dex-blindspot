"""Emulator-only smoke test for the Pilot B test-app pair.

Installs each APK on the running emulator, pre-grants runtime permissions via
adb, sets a mock GPS fix, taps each of the five labelled buttons, and saves a
screenshot after each tap to results/pilotB/screens/. Refuses to run unless
the only connected device is an emulator.

Usage: python pilotB_flutter/smoke_test.py
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADB = str(Path.home() / "Library/Android/sdk/platform-tools/adb")
SCREENS = ROOT / "results" / "pilotB" / "screens"
APPS = {
    "native": ("pilotB_flutter/apks/native.apk", "com.johnwogu.pilot.nativeapp"),
    "native_r8": ("pilotB_flutter/apks/native_r8.apk", "com.johnwogu.pilot.nativeapp"),
    "flutter_default": ("pilotB_flutter/apks/flutter_default.apk", "com.johnwogu.pilot.flutter"),
    "flutter_obfuscated": ("pilotB_flutter/apks/flutter_obfuscated.apk", "com.johnwogu.pilot.flutter"),
}
PERMISSIONS = ["android.permission.ACCESS_FINE_LOCATION",
               "android.permission.ACCESS_COARSE_LOCATION",
               "android.permission.READ_CONTACTS"]
BUTTONS = ["1. Read location", "2. Count contacts", "3. POST to httpbin",
           "4. File write/read", "5. Show masked key"]
GEO = ("-123.2460", "49.2606")  # lon, lat
AVD = "pilot_b_api36"  # dedicated clean AVD (see LOG.md)
SERIAL: list[str] = []


def adb(*args: str, binary: bool = False):
    out = subprocess.run([ADB, *SERIAL, *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode(errors="replace")


def select_emulator() -> None:
    """Target the emulator running AVD; never touch physical devices."""
    devices = [l.split()[0] for l in adb("devices").splitlines()[1:] if l.strip().endswith("device")]
    for d in devices:
        if d.startswith("emulator-") and adb("-s", d, "emu", "avd", "name").splitlines()[0].strip() == AVD:
            SERIAL[:] = ["-s", d]
            return
    raise SystemExit(f"refusing to run: no emulator running AVD {AVD} (devices: {devices})")


def ui_nodes() -> list[ET.Element]:
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    return list(ET.fromstring(adb("shell", "cat", "/sdcard/ui.xml")).iter("node"))


def node_text(n: ET.Element) -> str:
    return n.get("text") or n.get("content-desc") or ""


def tap_label(label: str) -> None:
    for _ in range(5):
        for n in ui_nodes():
            if node_text(n).strip().lower() == label.lower():  # native Buttons render ALL CAPS
                x1, y1, x2, y2 = map(int, re.findall(r"\d+", n.get("bounds")))
                adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
                return
        time.sleep(1)
    raise RuntimeError(f"button not found: {label}")


def dismiss_consent_dialog() -> None:
    """Decline Play Services' 'Location Accuracy' consent prompt (privacy-preserving choice).

    It is shown by the Fused Location Provider used by geolocator, not by app code.
    """
    for n in ui_nodes():
        if node_text(n).strip() == "No thanks":
            x1, y1, x2, y2 = map(int, re.findall(r"\d+", n.get("bounds")))
            adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
            print("  (declined Location Accuracy consent dialog)")
            return


def output_text() -> str:
    for n in ui_nodes():
        t = node_text(n)
        if "→" in t or t == "Tap a button.":
            return t
    return ""


def main() -> None:
    select_emulator()
    SCREENS.mkdir(parents=True, exist_ok=True)
    adb("emu", "geo", "fix", *GEO)
    results = {}
    for variant, (apk, pkg) in APPS.items():
        if pkg in adb("shell", "pm", "list", "packages"):
            adb("uninstall", pkg)
        for attempt in range(3):  # emulator /data is nearly full; installs occasionally fail
            try:
                adb("install", "-r", str(ROOT / apk))
                break
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
                time.sleep(5)
        for p in PERMISSIONS:
            adb("shell", "pm", "grant", pkg, p)
        adb("shell", "am", "start", "-W", "-n", f"{pkg}/.MainActivity")
        time.sleep(4)
        results[variant] = {}
        for i, label in enumerate(BUTTONS, 1):
            tap_label(label)
            # Wait for this button's result; for location, keep feeding GPS fixes.
            deadline = time.time() + (20 if i in (1, 3) else 5)
            while time.time() < deadline:
                if i == 1:
                    adb("emu", "geo", "fix", *GEO)
                    dismiss_consent_dialog()
                time.sleep(2)
                if output_text().startswith(f"{i}."):
                    break
            results[variant][label] = output_text()
            (SCREENS / f"{variant}_{i}.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
            print(f"{variant:20s} {results[variant][label]}")
        adb("shell", "am", "force-stop", pkg)
        adb("uninstall", pkg)
    (SCREENS / "smoke_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
