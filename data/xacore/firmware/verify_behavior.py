"""Replay the recovered M68000 routines against the published behavior vectors."""

import hashlib
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc, UcError
from unicorn.m68k_const import (
    UC_CPU_M68K_M68000,
    UC_M68K_REG_A7,
    UC_M68K_REG_D0,
    UC_M68K_REG_PC,
    UC_M68K_REG_SR,
)

FIRMWARE = Path(__file__).resolve().parent
ROOT = FIRMWARE.parents[2]
sys.path.insert(0, str(ROOT))
import edram

VARIANTS = {
    "ED16AA07": dict(
        state=0x1ECE8, output=0x1ECEC, entry=0x1EDC2, start=0x13206, emit=0x1355A,
        advance=0x13644, error=0x1312A, load=0x11B76, payload_sum=0x1ED02,
        copy_table=0x1A7F2, directory=0x1A842, builtin=0x1ED62, selector=0x1ED60,
        request=0x13CA0, incoming=0x1EDA6, channel_table=0x1DDA8,
    ),
    "EDRMAE11": dict(
        state=0x1E9B8, output=0x1E9BC, entry=0x1EA8E, start=0x13250, emit=0x1359E,
        advance=0x13688, error=0x1313A, load=0x11B86, payload_sum=0x1E9D2,
        copy_table=0x1A7C4, directory=0x1A814, builtin=0x1EA2E, selector=0x1EA2C,
        request=0x13CE4, incoming=0x1EA72, channel_table=0x1DA78,
    ),
}

BANK = 0x400000
BANK_SIZE = 0x40000
CONTEXT = 0x200000
STAGING = 0x220000
MESSAGE = 0x230000
STACK = 0x90000
RETURN_ADDRESS = 0x70000
PAGE_SIZE = 256
PLAYBACK_DONE = [["sequence_advance", None]]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Machine:
    def __init__(self, name):
        self.addr = VARIANTS[name]
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.uc.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        self.uc.mem_map(0, 0xC00000)
        self.uc.mem_write(0x400, (FIRMWARE / f"{name}.base-000400.bin").read_bytes())
        self.uc.reg_write(UC_M68K_REG_SR, 0x2000)
        self.put(self.addr["state"], CONTEXT)
        self.put(self.addr["output"], STAGING)
        self.put(CONTEXT + 0x36, BANK)
        self.put(CONTEXT + 0x3A, BANK)
        self.events = []
        self.hooks = {}
        self.uc.hook_add(UC_HOOK_CODE, self.visit)

    def visit(self, _uc, address, _size, _data):
        if address in self.hooks:
            self.hooks[address]()
        elif address == self.addr["advance"]:
            self.events.append(["sequence_advance", None])
            self.return_now()
        elif address == self.addr["error"]:
            stack = self.uc.reg_read(UC_M68K_REG_A7)
            self.events.append(["play_error", self.get(stack + 4) & 0xFF])
            self.return_now()

    def return_now(self):
        stack = self.uc.reg_read(UC_M68K_REG_A7)
        self.uc.reg_write(UC_M68K_REG_A7, stack + 4)
        self.uc.reg_write(UC_M68K_REG_PC, self.get(stack))

    def read(self, address, length):
        return bytes(self.uc.mem_read(address, length))

    def get(self, address, width=4):
        return int.from_bytes(self.read(address, width), "big")

    def put(self, address, value, width=4):
        self.uc.mem_write(address, value.to_bytes(width, "big"))

    def call(self, routine, *args, budget=400_000):
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.put(STACK, RETURN_ADDRESS)
        for i, value in enumerate(args, 1):
            self.put(STACK + i * 4, value)
        try:
            self.uc.emu_start(routine, RETURN_ADDRESS, count=budget)
        except UcError as exc:
            pc = self.uc.reg_read(UC_M68K_REG_PC)
            raise RuntimeError(f"68k fault at {pc:#x} in {routine:#x}: {exc}") from exc
        if self.uc.reg_read(UC_M68K_REG_PC) != RETURN_ADDRESS:
            raise RuntimeError(f"Instruction budget exhausted in {routine:#x}")

    def start_phrase(self, directory, slot):
        self.put(self.addr["entry"], directory + slot * 4)
        self.call(self.addr["start"])

    def page(self):
        self.uc.mem_write(STAGING, b"\xA5" * PAGE_SIZE)
        self.call(self.addr["emit"])
        return self.read(STAGING, PAGE_SIZE)


def synthetic_bank(segments, page_values):
    bank = bytearray(BANK_SIZE)
    descriptors = b"".join(struct.pack("<HBB", *segment) for segment in segments)
    directory = bytes((0, 1, len(segments)))
    bank[:4] = directory + bytes((-sum(directory + descriptors) % 256,))
    bank[256:256 + len(descriptors)] = descriptors
    for page, value in page_values:
        bank[page * PAGE_SIZE:(page + 1) * PAGE_SIZE] = bytes([value]) * PAGE_SIZE
    return bank


def trace_voice(name, bank, slot):
    machine = Machine(name)
    machine.uc.mem_write(BANK, bytes(bank))
    machine.start_phrase(BANK, slot)
    stream = bytearray()
    pages = []
    while not machine.events:
        if len(pages) >= 4096:
            raise RuntimeError("Phrase never completed")
        pages.append((machine.get(CONTEXT + 0x44) - BANK) // PAGE_SIZE
                     + machine.get(CONTEXT + 0x48, 2))
        stream.extend(machine.page())
    return bytes(stream), pages, machine.events


def trace_tone(name, slot, selector, low_memory_byte):
    machine = Machine(name)
    for i in range(4):
        address = machine.addr["copy_table"] + 10 * i
        source, target, words = struct.unpack(">IIH", machine.read(address, 10))
        machine.call(0xEA2A, source, target, words)
    directory = machine.addr["directory"]
    machine.put(1, low_memory_byte, 1)
    machine.put(CONTEXT + 0x36, directory)
    machine.put(CONTEXT + 0x3A, 0)
    machine.put(machine.addr["builtin"], directory)
    machine.put(machine.addr["selector"], selector, 2)
    machine.start_phrase(directory, slot)
    base = machine.get(CONTEXT + 0x3E)
    descriptors = [machine.read(base + 8 * i, 8) for i in range(3)]
    active = bytearray()
    words_per_record = []
    for descriptor in descriptors:
        address = int.from_bytes(descriptor[2:5], "big")
        words = machine.get(address, 2)
        duration = int.from_bytes(descriptor[5:], "big") * 8
        sample = machine.read(address + 2, words * 2)
        repeat_count = (duration + len(sample) - 1) // len(sample)
        active.extend((sample * repeat_count)[:duration])
        words_per_record.append(words)
    count = (len(active) + PAGE_SIZE - 1) // PAGE_SIZE
    stream = b"".join(machine.page() for _ in range(count))
    padded = active.ljust(count * PAGE_SIZE, b"\x00")
    return {
        "slot": slot, "active_codes": len(active), "staged_bytes": len(stream),
        "staged_sha256": sha256(stream), "active_sha256": sha256(stream[:len(active)]),
        "model_match": stream == padded, "descriptors": [d.hex() for d in descriptors],
        "source_record_words": words_per_record, "events": machine.events,
    }


def trace_load(name, case):
    machine = Machine(name)
    fill = b"\xA5" * BANK_SIZE
    machine.uc.mem_write(BANK, fill)
    begin = bytearray(22)
    begin[11] = case["bank_number"]
    begin[14:22] = b"TSTBANK1"
    packets = [(0x78, begin)]
    if "writes" in case:
        for offset, payload_hex in case["writes"]:
            message = bytearray(12) + bytes.fromhex(payload_hex)
            message[1] = len(message)
            message[9:12] = offset.to_bytes(3, "little")
            packets.append((0x7E, message))
        finish = bytearray(13)
        finish[9:13] = case["supplied_sum"].to_bytes(4, "big")
        packets.append((0x77, finish))
    packets.append((0x7F, b"\x00" * 16))
    queue = iter(packets)
    replies = []

    def receive():
        opcode, message = next(queue)
        machine.uc.mem_write(MESSAGE, bytes(message))
        machine.put(0xE222, MESSAGE)
        machine.uc.reg_write(UC_M68K_REG_D0, opcode)
        machine.return_now()

    def reply():
        stack = machine.uc.reg_read(UC_M68K_REG_A7)
        replies.append([machine.get(stack + i * 4) & 0xFF for i in (1, 2, 3)])
        machine.return_now()

    machine.hooks[0xFE56] = receive
    machine.hooks[0xFE8C] = reply
    machine.call(machine.addr["load"], 1, budget=1_600_000)
    assert all(args[1:] == [3, 12] for args in replies), replies
    result = {
        "replies": [args[0] for args in replies],
        "return": machine.uc.reg_read(UC_M68K_REG_D0) & 0xFF,
    }
    if "writes" in case:
        result.update(
            payload_sum=machine.get(machine.addr["payload_sum"]),
            bank_status=machine.get(0x1CD53, 1),
            registered_name=machine.read(0x1CD68, 8).hex(),
            before_window=machine.read(BANK + 0x6FE, 4).hex(),
            after_window=machine.read(BANK + 0xFFE, 4).hex(),
            protected_unchanged=machine.read(BANK + 0x700, 0x900) == fill[:0x900],
            first_page_cleared=machine.read(BANK, PAGE_SIZE) == bytes(PAGE_SIZE),
        )
    return result


def trace_request(name, frame):
    machine = Machine(name)
    machine.uc.mem_write(MESSAGE, frame)
    machine.put(machine.addr["incoming"], MESSAGE)
    machine.put(machine.addr["incoming"] + 4, len(frame))

    def release_buffer():
        machine.uc.reg_write(UC_M68K_REG_D0, 0)
        machine.return_now()

    machine.hooks[0x3F270] = release_buffer
    machine.call(machine.addr["request"])
    channel = machine.addr["channel_table"] + frame[2] * 0x68
    playlist_size = machine.get(channel + 0x2E)
    return {
        "playlist": machine.read(channel, playlist_size).hex(),
        "next_state": machine.get(channel + 0x2C, 1),
        "request_mode": machine.get(channel + 0x32, 1),
        "stored_flags": machine.get(channel + 0x33, 1),
    }


def verify(vectors):
    synthetic = vectors["ordinary"]["synthetic"]
    bank = synthetic_bank(synthetic["descriptors"], synthetic["page_values"])
    bad_bank = bytearray(bank)
    bad_bank[3] ^= 1
    archived = vectors["ordinary"]["archived"]
    image = edram.Image.read(ROOT / archived["file"])
    phrase = next(p for p in image.phrases() if p.bank == 0 and p.number == archived["slot"])
    pcm, _ = edram.render(image, phrase)

    for name, digest in vectors["firmware_sha256"].items():
        assert sha256((FIRMWARE / f"{name}.base-000400.bin").read_bytes()) == digest
        stream, pages, events = trace_voice(name, bank, synthetic["slot"])
        assert (len(stream), sha256(stream), pages, events) == (
            synthetic["staged_bytes"], synthetic["staged_sha256"],
            synthetic["source_pages"], PLAYBACK_DONE,
        ), name
        assert list(stream[::PAGE_SIZE]) == synthetic["staged_first_bytes"], name
        assert trace_voice(name, bad_bank, synthetic["slot"]) == (
            b"", [], vectors["ordinary"]["bad_checksum"]["events"],
        ), name
        stream, _pages, events = trace_voice(name, image.data, archived["slot"])
        assert (len(stream), sha256(stream), events) == (
            archived["staged_bytes"], archived["staged_sha256"], PLAYBACK_DONE,
        ), name
        assert edram.decode(stream) == pcm, name

        for case in vectors["loader"]:
            expected = case.get("by_firmware", {}).get(name, case.get("expected"))
            assert trace_load(name, case) == expected, (name, case["name"])
        for case in vectors["requests"]:
            assert trace_request(name, bytes.fromhex(case["frame"])) == case["expected"], (
                name, case["frame"],
            )

        tone = vectors["builtin_tones"]
        for case in tone["slots"]:
            assert trace_tone(name, case["slot"], tone["selector"], tone["low_memory_byte"]) == case, (
                name, case["slot"],
            )
        case = tone["alternate_low_memory"]["slot_result"]
        assert trace_tone(name, case["slot"], tone["selector"],
                          tone["alternate_low_memory"]["value"]) == case, name
        print(f"{name}: phrase staging, loader, request and built-in tone vectors matched")


if __name__ == "__main__":
    verify(json.loads((FIRMWARE / "playback-vectors.json").read_text(encoding="utf-8")))
