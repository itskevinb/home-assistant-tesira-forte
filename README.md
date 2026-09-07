# Biamp Tesira — Home Assistant integration

A native (config-flow) Home Assistant integration for **Biamp Tesira** DSPs
(built and tested on a **Tesira FORTE**). It holds one persistent
[Tesira Text Protocol](https://support.biamp.com/Tesira/Control/Tesira_Text_Protocol)
(TTP) session to the DSP on TCP port 23 and mirrors the blocks you name into HA
as `number`, `switch`, `sensor` and `binary_sensor` entities.

No broker, no add-on, no external bridge — it runs in-process and pushes state
via TTP `subscribe`, so edits made in Tesira software or by logic blocks show up
in HA too.

## Install

**HACS → ⋮ → Custom repositories** → add `https://github.com/itskevinb/home-assistant-tesira-forte`
as an **Integration** → install → restart Home Assistant.

Or copy `custom_components/tesira_forte/` into your `config/custom_components/`.

Then **Settings → Devices & Services → Add Integration → Biamp Tesira** and enter
the DSP's control-network IP (port 23).

> TTP on the Tesira is **unauthenticated**. Keep the control port on a trusted VLAN.

## The design is auto-discovered

On setup the integration connects and reads the **running design** off the device
— `SESSION get aliases` lists every instance tag, and each block is then probed
(`get numInputs` / `numChannels` / `crosspointLevel` / `gain` …) to work out its
kind and size. The setup flow shows you the result as an editable JSON list so
you can **trim or tweak it before it's saved** (discovery errs toward including a
block; EQ / filter / generator / crossover blocks that expose nothing drivable
are left out automatically).

Afterwards, edit the list any time in **the integration's ⚙ → Configure**, or
tick **Re-discover from device** there to pull it again.

A `tesira_forte:` block in `configuration.yaml` (see below) still works and, if
present, seeds an entry that has no design of its own.

The design is a **JSON list of blocks**, each `{"tag": "<instanceTag>", "kind":
"<kind>", …size}`:

| kind | size field(s) | entities created per unit |
|---|---|---|
| `aecinput` | `channels` | `gain` (number, 0–66 dB) + `phantomPower` (switch) |
| `input` | `channels` | same as `aecinput` (Mic/Line Input block) |
| `meter` | `channels` | `level` (sensor, dB, 500 ms push) |
| `level` | `channels` | `level` (number, −100…+12 dB) + `mute` (switch) |
| `mute` | `channels` | `mute` (switch) |
| `standardmixer` | `inputs`, `outputs` | input & output level + mute, `crosspoint` route (switch) |
| `matrixmixer` | `inputs`, `outputs` | input & output level + mute, per-crosspoint `crosspointLevel` (number) + `crosspointLevelState` (switch) |

Plus, always: a **Fault** binary_sensor (`problem`), a **Fault detail** sensor,
and a **Firmware** sensor.

### Finding an instance tag by hand

Discovery names blocks for you, but if you're adding one manually: in **Tesira
software**, right-click a processing block → **Properties** — the **Instance
Tag** is what goes in `"tag"`. (Or select a block and read the Instance Tag
field in the ribbon.) The tag is what TTP addresses, e.g. `Mixer1 get
inputLevel 1`.

### Example

```json
[
  { "tag": "Mic1",   "kind": "input",        "channels": 2 },
  { "tag": "Program", "kind": "level",       "channels": 2 },
  { "tag": "AudioMeter1", "kind": "meter",   "channels": 2 },
  { "tag": "Matrix1", "kind": "matrixmixer", "inputs": 4, "outputs": 4 }
]
```

### YAML (optional)

Used as the default for any config entry that has no design set in its options —
handy for a single-DSP install:

```yaml
tesira_forte:
  design:
    - { tag: Mic1, kind: input, channels: 2 }
    - { tag: Matrix1, kind: matrixmixer, inputs: 4, outputs: 4 }
```

## Notes

- Mic gain on an AEC/Mic-Line input is a discrete 6 dB-step preamp; the number
  entity is clamped to that grid. It's also the one attribute Tesira won't let
  you `subscribe` to, so it's polled (30 s + immediately after a write).
- Levels use the Tesira −100…+12 dB fader range.
- The fault poll (15 s) doubles as the session keepalive; a stalled session
  reconnects with exponential backoff and re-subscribes everything.
- If your firmware rejects `subscribe` on an attribute this integration expects
  to be subscribable, please open an issue with the model + firmware version.

## License

MIT
