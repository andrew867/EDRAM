"""Built-in tone playback from the two recovered 68000 loads."""

from dataclasses import dataclass
import hashlib
import struct

LOAD_ADDRESS = 0x400
SELECTORS = (0x4040, 0x5050)
LOW_MEMORY_BYTE = 1
PAGE_SIZE = 256
BANK_BASE = 0x400000
BANK_SIZE = 0x40000
STARTUP_BANKS = 8
PROTECTED_START = 0x0700
PROTECTED_END = 0x1000
RELOCATED_TABLE = 0x480000
MULAW = "mulaw-unmasked"
ALAW = "alaw-unmasked"
CUES = {1: "750 Hz test tone", 2: "Three-burst 750 Hz prompt"}
PAGE_SLOTS = {0: "Startup silence", **CUES, 3: "Short silence"}
CONTINUOUS_SLOTS = {slot: f"Built-in continuous tone {slot}" for slot in range(4, 8)}

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
class Continuous:
    slot: int
    codes: bytes
    components: tuple[Component, ...]

    @property
    def record_bytes(self):
        return (len(self.codes) // 2).to_bytes(2, "big") + self.codes


@dataclass(frozen=True)
class StartupCopy:
    source: int
    address: int
    words: int


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
        self.startup_copies = tuple(
            StartupCopy(source, address, words)
            for source, address, words in struct.iter_unpack(">IIH", self.read(copy_table, 80))
            if words
        )
        self.protected = [bytearray(PROTECTED_END - PROTECTED_START) for _ in range(STARTUP_BANKS)]
        for copy in self.startup_copies:
            data = self.read(copy.source, copy.words * 2)
            bank, offset = divmod(copy.address - BANK_BASE, BANK_SIZE)
            if not 0 <= bank < STARTUP_BANKS or not PROTECTED_START <= offset <= PROTECTED_END - len(data):
                raise ValueError(f"invalid firmware startup copy at 0x{copy.address:06x}")
            self.waveforms[copy.address] = data
            start = offset - PROTECTED_START
            self.protected[bank][start:start + len(data)] = data
        stored = {int.from_bytes(address, "big")
                  for slot in range(4, 40)
                  for _, address, _ in struct.iter_unpack(">H3s3s", self.descriptors(slot))}
        self.waveform_addresses = stored | {address + 0x80000 for address in stored}

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

    def startup_read(self, address, size):
        bank, offset = divmod(address - BANK_BASE, BANK_SIZE)
        if not 0 <= bank < STARTUP_BANKS or not PROTECTED_START <= offset <= PROTECTED_END - size:
            raise ValueError(f"address 0x{address:06x} is outside initialized startup RAM")
        start = offset - PROTECTED_START
        return bytes(self.protected[bank][start:start + size])

    def waveform(self, address):
        if address not in self.waveform_addresses:
            raise ValueError(f"unknown startup waveform record at 0x{address:06x}")
        return self.record(address), ALAW if address >= RELOCATED_TABLE else MULAW

    def resolve_first(self, address, bank_offset):
        return address + (0x80000 if self.selector == 0x5050 else bank_offset)

    def pages(self, slot, ranges, *, read=None, codec=MULAW):
        read = read or self.startup_read
        components = []
        chunks = []
        for address, pages, repeats in ranges:
            size = pages * PAGE_SIZE
            raw = read(address, size)
            zero_at = 0x0D00 - (address - BANK_BASE) % BANK_SIZE
            if 0 <= zero_at < size:
                raw = raw[:zero_at] + bytes(PAGE_SIZE) + raw[zero_at + PAGE_SIZE:]
            chunks.append(raw * repeats)
            components.append(CueRange(address, pages, repeats, size * repeats, codec))
        return Cue(slot, b"".join(chunks), tuple(components))

    def cue(self, slot, *, read=None):
        if slot not in PAGE_SLOTS:
            raise ValueError("built-in page slot must be from 0 to 3")
        ranges = ((page * PAGE_SIZE, pages, repeats)
                  for page, pages, repeats in struct.iter_unpack("<HBB", self.descriptors(slot)))
        return self.pages(slot, ranges, read=read)

    def continuous(self, slot, *, bank_offset=0, waveform=None):
        descriptor = self.descriptors(slot)
        if len(descriptor) != 8 or descriptor[:2] != bytes(2) or descriptor[5:] != b"\xff" * 3:
            raise ValueError(f"slot {slot} is not a continuous waveform")
        stored = int.from_bytes(descriptor[2:5], "big")
        resolved = self.resolve_first(stored, bank_offset)
        raw, codec = (waveform or self.waveform)(resolved)
        return Continuous(slot, raw, (Component(stored, resolved, len(raw) // 2, len(raw), codec),))

    def sit(self, number, *, bank_offset=0, waveform=None):
        if not 1 <= number <= 32:
            raise ValueError("SIT number must be from 1 to 32")
        slot = number + 7
        descriptors = self.descriptors(slot)
        if len(descriptors) != 24:
            raise ValueError(f"unsupported built-in SIT directory entry for slot {slot}")
        components = []
        chunks = []
        for i, (marker, address, duration) in enumerate(struct.iter_unpack(">H3s3s", descriptors)):
            quanta = int.from_bytes(duration, "big")
            if marker or quanta not in (0x112, 0x17C):
                raise ValueError(f"unsupported built-in SIT descriptor for slot {slot}")
            stored = int.from_bytes(address, "big")
            # The in-buffer transitions use the later addresses directly.
            resolved = stored if i else self.resolve_first(stored, bank_offset)
            raw, codec = (waveform or self.waveform)(resolved)
            samples = quanta * 8
            cycles = (samples + len(raw) - 1) // len(raw)
            chunks.append((raw * cycles)[:samples])
            components.append(Component(stored, resolved, len(raw) // 2, samples, codec))
        return SIT(slot, b"".join(chunks), tuple(components))
