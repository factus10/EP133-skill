#!/usr/bin/env python3
"""
EP-133 K.O. II Project File Creator

Creates .ppak files for the Teenage Engineering EP-133 sampler.
"""

import struct
import tarfile
import zipfile
import io
import json
import os
import re
import shutil
import wave
from datetime import datetime
from typing import Dict, List, Tuple, Optional


class EP133Project:
    """Create EP-133 project files (.ppak)"""

    def __init__(self, device_sku: str = "TE032AS001", project_num: int = 1,
                 bpm: Optional[float] = None):
        """
        Initialize a new EP-133 project.

        Args:
            device_sku: Device serial number (get from user's backup meta.json)
            project_num: Project slot 1-9
            bpm: Project tempo. None keeps the template's tempo (or 120 without a template)
        """
        self.device_sku = device_sku
        self.project_num = project_num
        self.bpm = bpm
        self.pad_assignments: Dict[str, Dict[int, int]] = {
            'a': {}, 'b': {}, 'c': {}, 'd': {}
        }
        # events are (time, pad, velocity, duration)
        self.patterns: Dict[str, List[Tuple[int, int, int, int]]] = {
            'a01': [], 'b01': [], 'c01': [], 'd01': []
        }
        self.pattern_bars: Dict[str, int] = {}
        # scenes: (pattern A, B, C, D, time-sig numerator, denominator); song: 1-based scene numbers
        self.scenes: List[Tuple[int, int, int, int, int, int]] = []
        self.song: List[int] = []
        self._template_pads = None
        self._template_settings = None
        self._template_scenes = None

    def load_template(self, backup_path: str):
        """
        Load pad and settings templates from an existing backup.
        This preserves pad parameters and settings that we don't fully understand.

        Args:
            backup_path: Path to .ppak or extracted backup directory
        """
        if backup_path.endswith('.ppak') or backup_path.endswith('.pak'):
            # Extract from archive
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(backup_path, 'r') as zf:
                    zf.extractall(tmpdir)
                # Find and extract tar
                for root, dirs, files in os.walk(tmpdir):
                    for f in files:
                        if f.endswith('.tar'):
                            tar_path = os.path.join(root, f)
                            with tarfile.open(tar_path, 'r') as tar:
                                tar.extractall(tmpdir)
                            break
                self._load_templates_from_dir(tmpdir)
        else:
            self._load_templates_from_dir(backup_path)

    def _load_templates_from_dir(self, dir_path: str):
        """Load templates from extracted directory"""
        self._template_pads = {}
        for group in ['a', 'b', 'c', 'd']:
            self._template_pads[group] = {}
            for pad in range(1, 13):
                pad_path = os.path.join(dir_path, 'pads', group, f'p{pad:02d}')
                if os.path.exists(pad_path):
                    with open(pad_path, 'rb') as f:
                        self._template_pads[group][pad] = bytearray(f.read())

        settings_path = os.path.join(dir_path, 'settings')
        if os.path.exists(settings_path):
            with open(settings_path, 'rb') as f:
                self._template_settings = f.read()

        scenes_path = os.path.join(dir_path, 'scenes')
        if os.path.exists(scenes_path):
            with open(scenes_path, 'rb') as f:
                data = f.read()
            if len(data) == SCENES_SIZE:
                self._template_scenes = data

    def assign_sample(self, group: str, pad: int, sample_num: int):
        """
        Assign a sample to a pad.

        Args:
            group: 'a', 'b', 'c', or 'd'
            pad: Pad number 1-12
            sample_num: Sample number (matches filename prefix, e.g., 001, 100, 405)
        """
        if group not in ['a', 'b', 'c', 'd']:
            raise ValueError(f"Invalid group: {group}. Must be 'a', 'b', 'c', or 'd'")
        if not 1 <= pad <= 12:
            raise ValueError(f"Invalid pad: {pad}. Must be 1-12")
        self.pad_assignments[group][pad] = sample_num

    @staticmethod
    def _check_pattern_name(pattern: str):
        m = re.fullmatch(r'([abcd])(\d\d)', pattern)
        if not m or not 1 <= int(m.group(2)) <= 99:
            raise ValueError(f"Invalid pattern: {pattern}. Must be a01-a99, b01-b99, c01-c99 or d01-d99")

    def set_pattern_bars(self, pattern: str, bars: int):
        """
        Set a pattern's length in bars (1-99, default 1). Stored in header byte 1.

        Args:
            pattern: Pattern name, e.g. 'a01' or 'b12'
            bars: Length in bars
        """
        self._check_pattern_name(pattern)
        if not 1 <= bars <= 99:
            raise ValueError(f"Invalid bars: {bars}. Must be 1-99")
        too_late = [e for e in self.patterns.get(pattern, []) if e[0] >= bars * TICKS_PER_BAR]
        if too_late:
            raise ValueError(f"{pattern} has events past bar {bars}")
        self.patterns.setdefault(pattern, [])
        self.pattern_bars[pattern] = bars

    def add_event(self, pattern: str, time: int, pad: int, velocity: int = 100,
                  duration: int = 16):
        """
        Add an event to a pattern.

        Args:
            pattern: Pattern name, e.g. 'a01' (group A, pattern 1) or 'b12'
            time: Time position in ticks (0 to bars*384-1; see set_pattern_bars)
            pad: Pad number 1-12
            velocity: Velocity 0-127 (default 100)
            duration: Note length in ticks (default 16; 24 = one 16th step)
        """
        self._check_pattern_name(pattern)
        bars = self.pattern_bars.get(pattern, 1)
        max_time = bars * TICKS_PER_BAR - 1
        if not 0 <= time <= max_time:
            raise ValueError(f"Invalid time: {time}. Must be 0-{max_time} for a {bars}-bar pattern")
        if not 1 <= pad <= 12:
            raise ValueError(f"Invalid pad: {pad}. Must be 1-12")
        if not 0 <= velocity <= 127:
            raise ValueError(f"Invalid velocity: {velocity}. Must be 0-127")
        if not 1 <= duration <= 0xFFFF:
            raise ValueError(f"Invalid duration: {duration}. Must be 1-65535 ticks")

        self.patterns.setdefault(pattern, []).append((time, pad, velocity, duration))

    def add_scene(self, a: int = 1, b: int = 1, c: int = 1, d: int = 1,
                  numerator: int = 4, denominator: int = 4) -> int:
        """
        Append a scene: which pattern number each group plays (1-99) plus a time signature.
        Scene 1 is the one the device shows on load. Returns the new scene's number.
        """
        if len(self.scenes) >= 99:
            raise ValueError("Maximum is 99 scenes")
        for n in (a, b, c, d):
            if not 1 <= n <= 99:
                raise ValueError(f"Invalid pattern number in scene: {n}. Must be 1-99")
        self.scenes.append((a, b, c, d, numerator, denominator))
        return len(self.scenes)

    def set_song(self, scene_numbers: List[int]):
        """
        Set the song list: up to 99 positions, each a 1-based scene number.
        Each position lasts as long as the longest pattern in its scene.
        """
        if len(scene_numbers) > 99:
            raise ValueError("Maximum is 99 song positions")
        self.song = list(scene_numbers)

    def _create_scenes_data(self) -> bytes:
        """Build the 712-byte scenes member (see references/format-details.md)."""
        for n in self.song:
            if not 1 <= n <= len(self.scenes):
                raise ValueError(f"Song refers to scene {n}, but only {len(self.scenes)} scenes exist")
        if self._template_scenes:
            data = bytearray(self._template_scenes)   # keeps the device's own header/trailer bytes
        else:
            data = bytearray(SCENES_SIZE)
            data[0:7] = bytes([0, 0, 0, 0, 0, 4, 4])
        for i in range(99):
            chunk = self.scenes[i] if i < len(self.scenes) else (0, 0, 0, 0, 4, 4)
            data[7 + 6 * i: 13 + 6 * i] = bytes(chunk)
        t = SCENES_TRAILER
        data[t + 3] = len(self.scenes)
        data[t + 11] = len(self.song)
        data[t + 12: t + 111] = bytes(self.song).ljust(99, b'\0')
        return bytes(data)

    def add_kick(self, pattern: str, time: int, pad: int = 10, velocity: int = 127):
        """Convenience method for adding kick drum hits"""
        self.add_event(pattern, time, pad, velocity)

    def add_snare(self, pattern: str, time: int, pad: int = 7, velocity: int = 120):
        """Convenience method for adding snare hits"""
        self.add_event(pattern, time, pad, velocity)

    def add_hihat(self, pattern: str, time: int, pad: int = 5, velocity: int = 90):
        """Convenience method for adding hi-hat hits"""
        self.add_event(pattern, time, pad, velocity)

    def _create_pattern_data(self, events: List[Tuple[int, int, int, int]], bars: int = 1) -> bytes:
        """Convert event list to binary pattern data"""
        events = sorted(events, key=lambda x: x[0])

        if len(events) > 255:
            raise ValueError(f"Too many events: {len(events)}. Maximum is 255")

        # header: 0x00, bars, event count, 0x00
        data = bytes([0x00, bars, len(events), 0x00])

        for time, pad, velocity, duration in events:
            row = (pad - 1) * 8
            col = 0x3c  # Standard playback
            # time u16, pad, note, velocity, duration u16 (ticks), flags
            data += struct.pack('<HBBBHB', time, row, col, velocity, duration, 0x00)

        return data

    def _create_pad_data(self, group: str, pad: int,
                         sample_frames: Optional[Dict[int, int]] = None) -> bytes:
        """Create binary pad data (layout in references/format-details.md)"""
        template = (self._template_pads or {}).get(group, {}).get(pad)
        sample_num = self.pad_assignments[group].get(pad)
        if template is not None:
            data = bytearray(template)
            if sample_num is None:
                return bytes(data)           # untouched pad: keep exactly as the device wrote it
            if int.from_bytes(data[1:3], 'little') == sample_num:
                return bytes(data)           # same sample: keep its trim and settings
        else:
            data = bytearray(DEFAULT_PAD)
            sample_num = sample_num or 0

        data[1:3] = struct.pack('<H', sample_num)
        # New sample: the trim (bytes 4-11) must cover it, or the pad is silent / cut off
        frames = (sample_frames or {}).get(sample_num)
        if frames:
            data[4:12] = (0).to_bytes(4, 'little') + min(frames, 0xFFFFFF).to_bytes(3, 'little') + b'\0'
        else:
            data[4:12] = b'\xff' * 8        # the device's own "untrimmed" marker
        return bytes(data)

    def _create_settings_data(self) -> bytes:
        """Settings from the template (tempo patched) or device-like defaults."""
        if self._template_settings:
            data = bytearray(self._template_settings)
        else:
            data = bytearray(DEFAULT_SETTINGS)
        if self.bpm is not None:
            if not 1 <= self.bpm <= 300:
                raise ValueError(f"Invalid bpm: {self.bpm}")
            data[4:8] = struct.pack('<f', self.bpm)
        return bytes(data)

    @staticmethod
    def _sample_frames(sounds_dir: Optional[str]) -> Dict[int, int]:
        """Map sample number -> frame count for 'NNN name.wav' files in sounds_dir."""
        frames: Dict[int, int] = {}
        if sounds_dir and os.path.isdir(sounds_dir):
            for fname in os.listdir(sounds_dir):
                m = re.match(r'(\d{1,3})\D', fname)
                if m and fname.lower().endswith('.wav'):
                    try:
                        with wave.open(os.path.join(sounds_dir, fname)) as w:
                            frames[int(m.group(1))] = w.getnframes()
                    except (wave.Error, EOFError):
                        pass
        return frames

    def save(self, output_path: str, sounds_dir: Optional[str] = None):
        """
        Save the project as a .ppak file.

        Args:
            output_path: Output .ppak file path
            sounds_dir: Directory containing .wav sound files (optional)
        """
        import tempfile

        with tempfile.TemporaryDirectory() as work_dir:
            # Create directory structure
            for group in ['a', 'b', 'c', 'd']:
                os.makedirs(os.path.join(work_dir, 'pads', group), exist_ok=True)
            os.makedirs(os.path.join(work_dir, 'patterns'), exist_ok=True)

            # Write pad files
            sample_frames = self._sample_frames(sounds_dir)
            for group in ['a', 'b', 'c', 'd']:
                for pad in range(1, 13):
                    pad_path = os.path.join(work_dir, 'pads', group, f'p{pad:02d}')
                    with open(pad_path, 'wb') as f:
                        f.write(self._create_pad_data(group, pad, sample_frames))

            # Write pattern files
            patterns = dict(self.patterns)
            # every pattern a scene refers to must exist as a member
            for scene in self.scenes:
                for group, num in zip('abcd', scene[:4]):
                    patterns.setdefault(f'{group}{num:02d}', [])
            for pattern_name, events in sorted(patterns.items()):
                pattern_path = os.path.join(work_dir, 'patterns', pattern_name)
                with open(pattern_path, 'wb') as f:
                    f.write(self._create_pattern_data(events, self.pattern_bars.get(pattern_name, 1)))

            if self.scenes:
                with open(os.path.join(work_dir, 'scenes'), 'wb') as f:
                    f.write(self._create_scenes_data())

            # Write settings
            settings_path = os.path.join(work_dir, 'settings')
            with open(settings_path, 'wb') as f:
                f.write(self._create_settings_data())

            # Create tar
            tar_buffer = io.BytesIO()
            orig_dir = os.getcwd()
            os.chdir(work_dir)
            try:
                with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                    tar.add('pads')
                    tar.add('patterns')
                    if self.scenes:
                        tar.add('scenes')
                    tar.add('settings')
            finally:
                os.chdir(orig_dir)
            tar_data = tar_buffer.getvalue()

            # Create meta.json
            meta = {
                "info": "teenage engineering - pak file",
                "pak_version": 1,
                "pak_type": "user",
                "pak_release": "1.2.0",
                "device_name": "EP-133",
                "device_sku": self.device_sku,
                "device_version": "2.0.5",
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "author": "Claude",
                "base_sku": self.device_sku
            }

            # Create .ppak (ZIP with leading slashes)
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add tar
                info = zipfile.ZipInfo(f'/projects/P{self.project_num:02d}.tar')
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, tar_data)

                # Add meta.json
                info = zipfile.ZipInfo('/meta.json')
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, json.dumps(meta, indent=2))

                # Add sounds
                if sounds_dir and os.path.isdir(sounds_dir):
                    for fname in sorted(os.listdir(sounds_dir)):
                        if fname.lower().endswith('.wav'):
                            fpath = os.path.join(sounds_dir, fname)
                            with open(fpath, 'rb') as sf:
                                info = zipfile.ZipInfo(f'/sounds/{fname}')
                                info.compress_type = zipfile.ZIP_DEFLATED
                                zf.writestr(info, sf.read())

        return output_path


# Default pad (27 bytes), modelled on factory pads: untrimmed, volume 100, release 255,
# one-shot, root note 60
DEFAULT_PAD = bytes([0, 0, 0, 0] + [0xFF] * 8 + [0, 0, 0, 0, 100, 0, 0, 0, 255, 0, 0, 0, 60, 0, 0])


def _default_settings() -> bytes:
    """224-byte settings as the device writes them: 120 BPM, -1.0 (unset) fader values."""
    data = bytearray(224)
    data[4:8] = struct.pack('<f', 120.0)
    for i in range(4):
        data[8 + 4 * i: 12 + 4 * i] = struct.pack('<f', 1.0)
    for i in range(48):
        data[24 + 4 * i: 28 + 4 * i] = struct.pack('<f', -1.0)
    data[216:224] = bytes([5, 5, 5, 5, 0, 1, 0, 0])   # fader assign FX x4; scale/root 0
    return bytes(data)


DEFAULT_SETTINGS = _default_settings()

# Scenes member layout (OS 2.5.1): 7-byte header, 99 x 6-byte scenes, 111-byte trailer
SCENES_SIZE = 712
SCENES_TRAILER = 7 + 99 * 6

# Timing constants
TICKS_PER_BAR = 384
TICKS_PER_BEAT = 96
TICKS_PER_8TH = 48
TICKS_PER_16TH = 24
TICKS_PER_32ND = 12


def beat_to_ticks(beat: float) -> int:
    """Convert beat number (1-indexed) to ticks. Beat 1 = tick 0."""
    return int((beat - 1) * TICKS_PER_BEAT)


def create_basic_beat(project: EP133Project,
                      kick_pad: int = 10,
                      snare_pad: int = 7,
                      hihat_pad: int = 5):
    """Add a basic 4/4 beat to pattern a01"""
    # Kick on 1 and 3
    project.add_event('a01', 0, kick_pad, 127)
    project.add_event('a01', 192, kick_pad, 127)

    # Snare on 2 and 4
    project.add_event('a01', 96, snare_pad, 120)
    project.add_event('a01', 288, snare_pad, 120)

    # Hi-hats on 8th notes
    for i in range(8):
        vel = 90 if i % 2 == 0 else 70
        project.add_event('a01', i * 48, hihat_pad, vel)


if __name__ == '__main__':
    # Example usage
    project = EP133Project(device_sku="TE032AS001", project_num=1)

    # Assign samples (example sample numbers)
    project.assign_sample('a', 10, 1)    # Kick
    project.assign_sample('a', 7, 100)   # Snare
    project.assign_sample('a', 5, 200)   # Hi-hat

    # Create a basic beat
    create_basic_beat(project)

    # Save
    project.save('example_beat.ppak')
    print("Created example_beat.ppak")
