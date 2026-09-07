"""Constants for the Biamp Tesira Forte integration."""

from __future__ import annotations

DOMAIN = "tesira_forte"

DEFAULT_PORT = 23

# Tesira fader / level range (dB). Confirmed from Mixer1/Mixer2
# inputMinLevel/inputMaxLevel on the running design.
LEVEL_MIN = -100.0
LEVEL_MAX = 12.0
LEVEL_STEP = 0.5

# AEC input mic pre-gain (dB). Discrete 6 dB steps, 0..66.
GAIN_MIN = 0
GAIN_MAX = 66
GAIN_STEP = 6

# How often to poll DEVICE activeFaultList (also acts as the TTP keepalive).
FAULT_POLL_INTERVAL = 15

# Meter subscription push rate (ms).
METER_RATE_MS = 500

# Running DSP design of the Music-Room Forte, enumerated by probing the live
# .tmf over TTP on 2026-09-06 (fw 5.7.0.12). Adjust if the layout changes and
# reload the integration.
DESIGN: dict[str, dict] = {
    "AecInput1": {"kind": "aecinput", "channels": 12},
    "AudioMeter1": {"kind": "meter", "channels": 2},
    "Mixer1": {"kind": "standardmixer", "inputs": 2, "outputs": 1},
    "Mixer2": {"kind": "matrixmixer", "inputs": 2, "outputs": 4},
}
