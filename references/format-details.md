# EP-133 File Format Complete Reference

## Official Device Specifications

Per the Teenage Engineering EP-133 User Guide (v2.0.5):

| Specification | Value |
|---------------|-------|
| Memory | 64 MB |
| Sample Slots | 999 |
| Pads | 12 × 4 groups |
| Sequencer Resolution | **96 PPQN (ticks per quarter note)** |
| Audio Input | 24-bit, SNR 96 dBA |
| Audio Output | 24-bit, SNR 98 dBA |
| MIDI | MMA Type A compliant |
| Sync | 8th, 16th, 24 PPQN modes |

Source: https://teenage.engineering/guides/ep-133/tech-specs

## meta.json Structure

```json
{
  "info": "teenage engineering - pak file",
  "pak_version": 1,
  "pak_type": "user",
  "pak_release": "1.2.0",
  "device_name": "EP-133",
  "device_sku": "TE032AS001",
  "device_version": "2.0.5",
  "generated_at": "2026-01-21T17:00:00.000Z",
  "author": "Claude",
  "base_sku": "TE032AS001"
}
```

**Critical**: `device_sku` and `base_sku` must match the target device. Extract from user's backup file.

## Pattern File Binary Format

### Header (4 bytes)
```
Byte 0: 0x00 (constant; must be 0)
Byte 1: Length in bars (uint8, 1-99)
Byte 2: Number of events (uint8, max 255)
Byte 3: 0x00 (constant)
```

Byte 1 is the pattern's length, not a constant. A 1-bar pattern has `0x01` here; a 2-bar pattern has `0x02` and its events run from tick 0 to 767.

### Event Structure (8 bytes each)
```
Offset  Size  Type      Description
------  ----  --------  -----------
0       2     uint16LE  Time position in ticks (0 to bars*384-1)
2       1     uint8     Row byte (pad identifier)
3       1     uint8     Column byte (0x3c = 60 for normal playback)
4       1     uint8     Velocity (0-127)
5       2     uint16LE  Note length in ticks (24 = one 16th step)
7       1     uint8     Flags (0x00 observed)
```

Patterns recorded on the device hold note lengths of 12-26 ticks at bytes 5-6. The older `0x10 0x00 0x00` value is a 16-tick note with no flags.

Events are sorted by time.

Some records in device-written patterns have a row byte that is not a multiple of 8. These look like automation records, not notes. Readers should skip them, and writers should not produce them. Byte 7 has also been seen non-zero on device-written notes; its meaning is unknown.

### Row Byte to Pad Mapping
```
Pad 1  = 0x00 (0)
Pad 2  = 0x08 (8)
Pad 3  = 0x10 (16)
Pad 4  = 0x18 (24)
Pad 5  = 0x20 (32)
Pad 6  = 0x28 (40)
Pad 7  = 0x30 (48)
Pad 8  = 0x38 (56)
Pad 9  = 0x40 (64)
Pad 10 = 0x48 (72)
Pad 11 = 0x50 (80)
Pad 12 = 0x58 (88)
```

Formula: `row_byte = (pad_number - 1) * 8`

### Column Byte

For standard drum playback, always use `0x3c` (60).

Other values may represent chromatic pitch offsets but can cause issues. Stick to 0x3c unless experimenting.

## Pad File Binary Format (27 bytes)

Field map from [phones24/ep133-export-to-daw](https://github.com/phones24/ep133-export-to-daw/blob/main/docs/EP133_FORMATS.md), checked against a device backup (OS 2.5.1):

```
Offset  Size  Description
------  ----  -----------
0       1     0x00
1       2     Sample number (uint16LE, 0 = no sample)
3       1     MIDI channel
4       3     Trim start, in sample frames (uint24LE)
7       1     0x00
8       3     Play length from trim start, in sample frames (uint24LE)
11      1     0x00
12      4     Time-stretch BPM (float32LE)
16      1     Volume (0-200, default 100)
17      1     Pitch, semitones (int8: -12..12)
18      1     Pan (int8: -16 left .. 0 centre .. 16 right)
19      1     Attack (0-255; KEY/LEG modes)
20      1     Release (0-255; default 255)
21      1     Time stretch: 0 off, 1 BPM, 2 bars, 3 rev
22      1     Choke group flag
23      1     Play mode: 0 one-shot, 1 key, 2 legato
24      1     Root note (MIDI note, default 60)
25      1     Time-stretch bars: 0 = 1, 1 = 2, 2 = 4, 255 = 1/2, 254 = 1/4
26      1     Pitch, fine (int8, hundredths of a semitone)
```

**Bytes 8-10 are the sample's play length, not a ROM address.** With trim start 0, the value equals the sample's frame count. In a real backup, all 12 pads of a group matched their WAV files exactly (e.g. sample 001 MICRO KICK: 22412 in the pad, 22412 frames in the WAV). A length of 0 plays nothing, which is why pads built from zeros are silent.

When you assign a different sample, set the trim to cover the new sample: trim start 0 and length = the WAV's frame count. Factory pads that have never been trimmed store `ff ff ff ff ff ff ff ff` in bytes 4-11 instead.

Some device-written pad files are 26 bytes (without byte 26).

### Assigning a Sample
```python
import struct

with open(pad_file, 'rb') as f:
    data = bytearray(f.read())

# Set sample number at bytes 1-2
data[1:3] = struct.pack('<H', sample_number)

with open(pad_file, 'wb') as f:
    f.write(data)
```

## Scenes File (712 bytes)

The `scenes` member holds the scenes and the song list (song mode). It goes in the project tar after the patterns and before `settings`. A project with no committed scenes has no `scenes` member, and the device uses default scenes.

Layout as observed on OS 2.5.1. Source: [kmorrill/ep-series-sysex](https://github.com/kmorrill/ep-series-sysex/blob/main/docs/project-format.md), and it matches a real device backup byte for byte:

```
Offset    Size     Description
--------  -------  -----------
0         7        Header (unknown; the device wrote 00 01 01 01 01 04 04, the
                   kmorrill doc observed 00 00 00 00 00 04 04). Preserve from a template.
7         99 x 6   Scenes 1-99, one 6-byte record each (scene n at 7 + 6*(n-1))
601       111      Trailer
```

### Scene record (6 bytes)
```
Byte 0: Group A pattern number (1-99; 0 = unused scene)
Byte 1: Group B pattern number
Byte 2: Group C pattern number
Byte 3: Group D pattern number
Byte 4: Time signature numerator   (literal, e.g. 4)
Byte 5: Time signature denominator (literal, e.g. 4)
```

Unused records must be `00 00 00 00 04 04`; zeroing the time signature gives `err scene 156`. Scene 1 is the scene the device loads as the current one.

### Trailer (111 bytes, file offset 601)
```
Trailer byte 3   (file 604):      Number of scenes in use
Trailer byte 11  (file 612):      Song length (number of song positions, 0-99)
Trailer byte 12+ (file 613-711):  Song list, one byte per position: a 1-based scene number
Other bytes:                      0x00 observed
```

Each song position plays its scene once. A position lasts as long as the longest pattern in that scene. So, to repeat a section, repeat its scene number in the song list.

To play the song on the device: hold MAIN and press the ENTER pad to open the song list editor, then press SHIFT + PLAY to play from position 1 (see the official guide, "song mode").

When a project has no `scenes` member, scene *n* plays pattern *n* in every group.

### Safety notes
- Only reference patterns that exist as members in the same project tar (`err pattern 187`). Write empty patterns (`00 01 00 00`) for scene slots you don't use.
- Prefer patching a `scenes` member from the user's own backup over building one from zeros. The header and trailer still have unknown bytes, and the kmorrill doc reports that a 2.0.5-era `scenes` member does not carry over to 2.5.1.
- Status: the scene records and song list are verified by decoding device-written files. Playback of a written song list on the device is not yet confirmed.

### Example: song with repeats
```
scenes:  1 = A01 intro, 2 = A02 verse, 3 = A03 fill
song:    1 1 2 2 2 3 2 2      (length byte = 8)
```

## Settings File (224 bytes)

The `settings` member is 224 bytes on OS 2.5.1. Older notes give 222. Field map from [phones24/ep133-export-to-daw](https://github.com/phones24/ep133-export-to-daw/blob/main/docs/EP133_FORMATS.md), checked against a device backup:

```
Offset    Size      Description
--------  --------  -----------
0         4         0x00
4         4         Tempo in BPM (float32LE). Must be non-zero
8         16        Four float32LE values, 1.0 on the device (meaning unconfirmed)
24        4 x 48    Group A, B, C, D blocks (group g at 24 + 48*g): 12 float32LE
                    fader parameter values each. -1.0 = not set / default
216       4         Fader assignment for groups A-D (0 LVL, 1 PTC, 2 TIM, 3 LPF, 4 HPF, 5 FX, ...)
220       2         Unknown (00 01 observed)
222       1         Scale (0 2T, 1 maj, 2 min, 3 dor, 4 phr, 5 lyd, 6 mix, 7 loc,
                    8 ma.p, 9 mi.p, 10 BLU, 11 H.MI, 12 M.MI)
223       1         Root note (pitch class: 0 C .. 11 B)
```

Prefer copying settings from the user's own backup and patching only the fields you need, such as the tempo.

## FX Settings File (`fx_settings`)

Holds the master effect when one is set. Field map from [phones24/ep133-export-to-daw](https://github.com/phones24/ep133-export-to-daw/blob/main/docs/EP133_FORMATS.md):
- Byte 4: effect type (0 off, 1 delay, 2 reverb, 3 distortion, 4 chorus, 5 filter, 6 compressor).
- Bytes 12 + 4*(type-1): parameter 1 of each effect, float32LE.
- Bytes 76 + 4*(type-1): parameter 2, float32LE.

A project with no effect set has no `fx_settings` member.

## Timing Reference (Official: 96 PPQN)

The EP-133 uses **96 ticks per quarter note** as its internal sequencer resolution. This is confirmed in the official Technical Specifications.

| Note Value | Ticks | At 120 BPM |
|------------|-------|------------|
| Whole note | 384   | 2000ms     |
| Half note  | 192   | 1000ms     |
| Quarter    | 96    | 500ms      |
| 8th note   | 48    | 250ms      |
| 16th note  | 24    | 125ms      |
| 32nd note  | 12    | 62.5ms     |
| Triplet 8th| 32    | 166ms      |

### Swing/Shuffle

For swing feel, offset alternate notes:
- Straight 8ths: 0, 48, 96, 144...
- Swung 8ths: 0, 52, 96, 148... (offset by ~4-8 ticks)

## ZIP Structure Requirements

**Critical**: All paths must start with `/` (leading slash)

```python
import zipfile

with zipfile.ZipFile('output.ppak', 'w', zipfile.ZIP_DEFLATED) as zf:
    # CORRECT - with leading slash
    info = zipfile.ZipInfo('/projects/P01.tar')
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, tar_data)

    # WRONG - will cause "PAK FILE IS EMPTY" error
    # zf.writestr('projects/P01.tar', tar_data)
```

## TAR Structure

Standard POSIX tar with no compression:

```python
import tarfile
import io

tar_buffer = io.BytesIO()
with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
    tar.add('pads')
    tar.add('patterns')
    tar.add('settings')
tar_data = tar_buffer.getvalue()
```

## Sound File Requirements

- Format: WAV (PCM)
- Sample rate: 44100 Hz recommended
- Bit depth: 16-bit or 24-bit
- Channels: Mono or Stereo
- Naming: `NNN name.wav` where NNN is 001-999

## Project Slots

EP-133 supports projects P01-P09. Specify in tar filename:
- `/projects/P01.tar` through `/projects/P09.tar`

## Complete Python Example

```python
import struct
import tarfile
import zipfile
import io
import json
import os

def create_pattern(events):
    """Create pattern binary from list of (time, pad, velocity) tuples"""
    if not events:
        return bytes([0x00, 0x01, 0x00, 0x00])

    events = sorted(events, key=lambda x: x[0])
    header = bytes([0x00, 0x01, len(events), 0x00])
    data = header

    for time, pad, velocity in events:
        row = (pad - 1) * 8
        col = 0x3c
        event = struct.pack('<H', time) + bytes([row, col, velocity, 0x10, 0x00, 0x00])
        data += event

    return data

def create_ppak(project_num, patterns, pad_assignments, sounds_dir, output_path,
                device_sku="TE032AS001", template_dir=None):
    """
    Create a complete .ppak file

    Args:
        project_num: 1-9
        patterns: dict of {'a01': [(time, pad, vel), ...], 'b01': [...], ...}
        pad_assignments: dict of {'a': {pad: sample, ...}, 'b': {...}, ...}
        sounds_dir: path to directory containing .wav files
        output_path: output .ppak path
        device_sku: device serial (get from user's backup)
        template_dir: optional path to template pads/settings
    """

    # Create working directory
    work_dir = '/tmp/ep133_work'
    os.makedirs(f'{work_dir}/pads/a', exist_ok=True)
    os.makedirs(f'{work_dir}/pads/b', exist_ok=True)
    os.makedirs(f'{work_dir}/pads/c', exist_ok=True)
    os.makedirs(f'{work_dir}/pads/d', exist_ok=True)
    os.makedirs(f'{work_dir}/patterns', exist_ok=True)

    # Create pad files (27 bytes each)
    pad_template = bytes([0x00] * 27)  # Minimal template
    for group in ['a', 'b', 'c', 'd']:
        for pad in range(1, 13):
            data = bytearray(pad_template)
            if group in pad_assignments and pad in pad_assignments[group]:
                sample = pad_assignments[group][pad]
                data[1:3] = struct.pack('<H', sample)
            with open(f'{work_dir}/pads/{group}/p{pad:02d}', 'wb') as f:
                f.write(data)

    # Create pattern files
    for pattern_name, events in patterns.items():
        with open(f'{work_dir}/patterns/{pattern_name}', 'wb') as f:
            f.write(create_pattern(events))

    # Create settings file (minimal)
    settings = bytes([0x00] * 222)
    with open(f'{work_dir}/settings', 'wb') as f:
        f.write(settings)

    # Create tar
    tar_buffer = io.BytesIO()
    os.chdir(work_dir)
    with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
        tar.add('pads')
        tar.add('patterns')
        tar.add('settings')
    tar_data = tar_buffer.getvalue()

    # Create meta.json
    meta = {
        "info": "teenage engineering - pak file",
        "pak_version": 1,
        "pak_type": "user",
        "pak_release": "1.2.0",
        "device_name": "EP-133",
        "device_sku": device_sku,
        "device_version": "2.0.5",
        "generated_at": "2026-01-21T12:00:00.000Z",
        "author": "Claude",
        "base_sku": device_sku
    }

    # Create final .ppak
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add tar with leading slash
        info = zipfile.ZipInfo(f'/projects/P{project_num:02d}.tar')
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, tar_data)

        # Add meta.json
        info = zipfile.ZipInfo('/meta.json')
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, json.dumps(meta, indent=2))

        # Add sounds
        for fname in os.listdir(sounds_dir):
            if fname.endswith('.wav'):
                with open(os.path.join(sounds_dir, fname), 'rb') as sf:
                    info = zipfile.ZipInfo(f'/sounds/{fname}')
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, sf.read())

    return output_path
```
