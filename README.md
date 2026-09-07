# Biamp Tesira Forte — Home Assistant integration

A native (config-flow) Home Assistant integration for the **Biamp Tesira FORTE**.
It keeps one persistent [Tesira Text Protocol](https://support.biamp.com/Tesira/Control/Tesira_Text_Protocol) (TTP)
session open to the DSP on TCP port 23 and mirrors its control surface into HA as
`number`, `switch`, `sensor` and `binary_sensor` entities.

No broker, no add-on, no external bridge — it runs in-process and pushes state via
TTP `subscribe`, so edits made in Tesira software or by logic blocks show up in HA
too.

## What it exposes

The DSP layout is baked into `const.py::DESIGN` (enumerated by probing the running
`.tmf`). The shipped map is for a Forte used as a mic preamp / small mixer:

| Tesira block | HA entities |
|---|---|
| `AecInput1` (12-ch AEC input) | per-channel **gain** (number, 0–66 dB / 6 dB steps) + **phantom power** (switch) |
| `AudioMeter1` (2-ch meter) | per-channel **level** (sensor, dB, 500 ms push) |
| `Mixer1` (Standard Mixer 2→1) | input level/mute, output level/mute, route crosspoints |
| `Mixer2` (Matrix Mixer 2→4) | input level/mute, output level/mute, per-crosspoint level + enable |
| `DEVICE` | **Fault** (binary_sensor, `problem`), **Fault detail** + **Firmware** (sensors) |

If your Forte runs a different design, edit `DESIGN` and reload the integration.

## Install

**HACS** → ⋮ → *Custom repositories* → add `https://github.com/itskevinb/home-assistant-tesira-forte`
as an *Integration* → install → restart HA.

Or copy `custom_components/tesira_forte/` into your `config/custom_components/`.

Then **Settings → Devices & Services → Add Integration → Biamp Tesira Forte** and
enter the DSP's control-network IP (port 23).

## Notes

- TTP on the Forte is **unauthenticated**. Keep the control port on a trusted VLAN.
- Mic gain is a discrete 6 dB-step preamp; the number entity is clamped to that grid.
- Levels use the Tesira −100…+12 dB fader range.
- The fault poll (15 s) doubles as the session keepalive; a stalled session
  reconnects with exponential backoff and re-subscribes everything.
