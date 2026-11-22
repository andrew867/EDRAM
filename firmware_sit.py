"""Built-in tone playback from the two recovered 68000 loads."""

from dataclasses import dataclass
import hashlib
import struct

LOAD_ADDRESS = 0x400
SELECTORS = (0x4040, 0x5050)
LOW_MEMORY_BYTE = 1
PAGE_SIZE = 256
MULAW = "mulaw-unmasked"
ALAW = "alaw-unmasked"
CUES = {1: "750 Hz test tone", 2: "Three-burst 750 Hz prompt"}
CLEARED_PAGE = 0x400700

# Flat image digest, then its directory and startup copy table addresses.
PROFILES = {
    "1592e002d42d7bd87afaacf7d735955c58c27bc6dbb8fe082621e845687cd1fb":
        ("ED16AA07", 0x1A842, 0x1A7F2),
    "8e8f4db21924fec38bae180246edff1e53e88e1fbcdd4bd4653e5b83cf361fd1":
        ("EDRMAE11", 0x1A814, 0x1A7C4),
}


@dataclass(frozen=True)
class Component:
    stored_address: int
    record_address: int
    record_words: int
    samples: int
    codec: str


@dataclass(frozen=True)
class SIT:
    slot: int
    codes: bytes
    components: tuple[Component, ...]

    @property
    def number(self):
        return self.slot - 7


@dataclass(frozen=True)
class CueRange:
    page_address: int
    pages: int
    repeats: int
    samples: int
    codec: str


@dataclass(frozen=True)
class Cue:
    slot: int
    codes: bytes
    components: tuple[CueRange, ...]


def coded_chunks(tone):
    offset = 0
    for part in tone.components:
        end = offset + part.samples
        yield tone.codes[offset:end], part.codec
        offset = end


class Firmware:
    def __init__(self, flat, selector=0x4040):
        self.sha256 = hashlib.sha256(flat).hexdigest()
        if self.sha256 not in PROFILES:
            raise ValueError("unsupported built-in SIT firmware image")
        if selector not in SELECTORS:
            raise ValueError("built-in SIT selector must be 0x4040 or 0x5050")
        self.name, self.directory, copy_table = PROFILES[self.sha256]
        self.selector = selector
        self.flat = flat
        self.waveforms = {}
        for i in range(4):
            entry = self.read(copy_table + 10 * i, 10)
            source, address, words = struct.unpack(">IIH", entry)
            self.waveforms[address] = self.read(source, words * 2)

    def read(self, address, length):
        start = address - LOAD_ADDRESS
        return self.flat[start:start + length]

    def record(self, address):
        for base, region in self.waveforms.items():
            if base <= address < base + len(region):
                offset = address - base
                words = int.from_bytes(region[offset:offset + 2], "big")
                start = offset + 2
                if words and start + words * 2 <= len(region):
                    return region[start:start + words * 2]
        raise ValueError(f"invalid firmware waveform record at 0x{address:06x}")

    def descriptors(self, slot):
        pointer, units, _ = struct.unpack("<HBB", self.read(self.directory + 4 * slot, 4))
        return self.read(self.directory + pointer, units * 4)

    def cue(self, slot):
        if slot not in CUES:
            raise ValueError("built-in cue slot must be 1 or 2")
        components = []
        codes = bytearray()
        for page, pages, repeats in struct.iter_unpack("<HBB", self.descriptors(slot)):
            address = page * PAGE_SIZE
            size = pages * PAGE_SIZE
            if address == CLEARED_PAGE and pages == 1:
                raw = bytes(PAGE_SIZE)
            else:
                raw = self.waveforms.get(address, b"")[:size]
                if len(raw) != size:
                    raise ValueError(f"missing firmware cue waveform at 0x{address:06x}")
            codes.extend(raw * repeats)
            components.append(CueRange(address, pages, repeats, size * repeats, MULAW))
        return Cue(slot, bytes(codes), tuple(components))

    def sit(self, number):
        if not 1 <= number <= 32:
            raise ValueError("SIT number must be from 1 to 32")
        slot = number + 7
        descriptors = self.descriptors(slot)
        if len(descriptors) != 24:
            raise ValueError(f"unsupported built-in SIT directory entry for slot {slot}")
        components = []
        codes = bytearray()
        for i in range(0, len(descriptors), 8):
            marker, address, duration = struct.unpack(">H3s3s", descriptors[i:i + 8])
            quanta = int.from_bytes(duration, "big")
            if marker or quanta not in (0x112, 0x17C):
                raise ValueError(f"unsupported built-in SIT descriptor for slot {slot}")
            stored_address = int.from_bytes(address, "big")
            # The in-page transitions read the later descriptor addresses directly.
            alternate = i == 0 and self.selector == 0x5050
            resolved = stored_address + (0x80000 if alternate else 0)
            codec = ALAW if alternate else MULAW
            waveform = self.record(resolved)
            samples = quanta * 8
            cycles = (samples + len(waveform) - 1) // len(waveform)
            codes.extend((waveform * cycles)[:samples])
            components.append(Component(stored_address, resolved, len(waveform) // 2, samples, codec))
        return SIT(slot, bytes(codes), tuple(components))
