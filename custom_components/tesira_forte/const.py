"""Constants for the Biamp Tesira integration."""

from __future__ import annotations

DOMAIN = "tesira_forte"

DEFAULT_PORT = 23

CONF_DESIGN = "design"

# Tesira fader / level range (dB). Matches the inputMinLevel/inputMaxLevel a
# Standard/Matrix Mixer reports; also the range of a Level Control block.
LEVEL_MIN = -100.0
LEVEL_MAX = 12.0
LEVEL_STEP = 0.5

# Analog mic pre-gain (dB) on an AEC Input / Mic-Line Input block: discrete
# 6 dB steps, 0..66.
GAIN_MIN = 0
GAIN_MAX = 66
GAIN_STEP = 6

# DEVICE activeFaultList poll interval (also the TTP keepalive).
FAULT_POLL_INTERVAL = 15

# AudioMeter subscription push rate (ms).
METER_RATE_MS = 500

# Supported DSP block kinds. A Tesira design is NOT discoverable over TTP, so
# the user declares their blocks (instance tag + kind + size) via the options
# flow or YAML; see README. Each entry: {"tag": <instanceTag>, "kind": <one of
# these>, ...size fields}.
#
#   aecinput / input   channels          -> per ch: gain (number), phantomPower (switch)
#   meter              channels          -> per ch: level (sensor, dB)
#   level              channels          -> per ch: level (number), mute (switch)
#   mute               channels          -> per ch: mute (switch)
#   standardmixer      inputs, outputs   -> in/out level+mute, crosspoint (switch)
#   matrixmixer        inputs, outputs   -> in/out level+mute, per-crosspoint
#                                           level (number) + crosspointLevelState (switch)
BLOCK_KINDS = frozenset(
    {"aecinput", "input", "meter", "level", "mute", "standardmixer", "matrixmixer"}
)

# Shipped as the default when nothing is configured. This is one real Forte
# used as a phantom-power mic pre feeding a small mixer -- replace it with your
# own design in the integration's options.
DEFAULT_DESIGN: list[dict] = [
    {"tag": "AecInput1", "kind": "aecinput", "channels": 12},
    {"tag": "AudioMeter1", "kind": "meter", "channels": 2},
    {"tag": "Mixer1", "kind": "standardmixer", "inputs": 2, "outputs": 1},
    {"tag": "Mixer2", "kind": "matrixmixer", "inputs": 2, "outputs": 4},
]
