# EDRAM behavior specification

This specification describes the announcement loader, phrase sequencer, and sample staging of Nortel `ED16AA07` and `EDRMAE11`. It is a handoff for a fresh implementation. The [C reference](../reference/edram/playback.c) models ordinary page playback and finite waveform playback. The [evidence notes](EDRAM_FIRMWARE_EVIDENCE.md) give the binary addresses, test setup, and unresolved dependencies.

## Compatibility boundary

An implementation accepts an incoming load or playback request, maintains announcement banks and per-channel playback state, and emits 256-byte blocks of eight-bit companded sample codes. At the nominal 8 kHz sample clock, a block represents 32 ms. Decode to linear PCM separately when needed. A network-side capture is needed to determine the physical PCM law and level.

The load messages below begin at the firmware's decoded receive buffer. The playback request layout begins at the application queue. The DMS switch supplies routing, CLLI resolution, and the outer command transport. The firmware also relies on resident 68k services for task scheduling, queues, timers, and interrupt return. An application-level model can supply those services through callbacks.

## Firmware download and startup

The primary application stub at `0x0412` runs the firmware-download handshake at `0x010106` when internal marker `0x0536` lacks `0x12345678`. After the `0x7D` start message and any `0x7E` data, the `0x77` finish compares the supplied sum with the sum of the executive prefix and application image. A match calls the stub at `0x0418`. Header word `0x0404 == 0x4342` also takes that branch. A mismatch without the header value rejects the transfer. In both recovered builds the `0x0418` path is reached during a successful ordinary firmware download. It clears nine pages at bank-relative `0x0700` in banks 0 through 7, copies the four nonempty entries in the eight-entry table, clears transfer workspace, sets the marker, and enters the executive handoff. On a subsequent primary entry the marker skips the download handshake. The resident continuation beyond `0x020D20` is outside the supplied image. [Trace and copy table](EDRAM_FIRMWARE_EVIDENCE.md#firmware-download-and-startup)

## Memory and file loading

- Each bank holds `0x40000` bytes. Physical bank index zero starts at `0x400000`, with the same stride for each successive bank.
- File records carry offsets within the load. A load starts at the selected bank and can cover consecutive banks. The protected region within the bank is `[0x0700, 0x1000)`.
- The firmware clears `[0, 0x0700)` and `[0x1000, 0x40000)` within the bank selected by the transaction high-water mark when its clear flag is unset. The payload copy clips against `[0x0700, 0x1000)` relative to the start of the load. In a packet crossing an edge, the payload index still corresponds to the original destination offset. The clear flag is part of each bank's directory state.
- The successful firmware download initializes the first eight protected RAM windows before announcement-bank loading. Keep the startup bytes when applying the first bank's protected write exclusion. Subsequent banks' payload addresses remain relative to the start of the transaction.

All byte positions in this table are zero-based within the receive buffer. Codes are hexadecimal.

| Request | Relevant fields | Behavior |
| --- | --- | --- |
| `78`, begin | Low six bits of byte 11 contain the one-based bank number. Bytes 14-21 hold the eight-byte name. | Valid bank numbers are 1-32 on ED16AA07 and 1-8 on EDRMAE11. Select the bank and reset the relative high-water offset and payload sum. Reply `70`. A zero or out-of-range bank produces `62`. |
| `7E`, data | Byte 1 minus 12 gives the payload byte count. Bytes 9-11 form a little-endian 24-bit offset. Payload starts at byte 12. | Update the high-water offset, clear the high-water bank's writable areas if its flag is unset, accumulate the original payload sum, and apply the writable portion of the packet. Reply `70` in an open session. |
| `77`, finish | Bytes 9-12 contain a big-endian 32-bit sum. | If the bytes at bank offset `0x0678` are ASCII `.bin`, compare the sum against the accumulated payload checksum. Mismatch replies `72` and leaves the bank unregistered. The other observed format branch acknowledges without that comparison. Successful finish replies `70` and registers the name and resolved range. |
| `7F`, exit | No payload used by the recovered load loop. | Exit the receive loop with return value `0x7F`. |

The reply helper receives the reply code followed by `3, 12`. The mode used by the test returns the selected zero-based bank number after successful registration. `G0/G2/G6` records, S-record text, and the FTFS record wrapper belong to the host file layer. [File formats](../FORMAT.md)

For the verified even-length packets, compute the payload sum by adding unsigned big-endian 16-bit words, modulo `2^32`. Add all data bytes before clipping the write. Runtime code uses a word-read loop and can read the following byte on an odd-length payload. The observed file suite should use aligned, complete records. For a new implementation, validate lengths, indices, and the packet span at the transport boundary. The write tests cover protected-window crossings and a factory load spanning multiple banks. The behavior of sparse out-of-order uploads still needs an independent trace.

```c
apply_data(session, relative_offset, payload, length)
{
    if (length == 0)
        return ACK;
    session.end = max(session.end, relative_offset + length - 1);
    clear_if_needed(session.first_bank + session.end / BANK_SIZE);
    session.payload_sum += sum_big_endian_words(payload, length);

    for (size_t i = 0; i < length; ++i) {
        size_t address = relative_offset + i;
        if (address < 0x700 || address >= 0x1000)
            memory[session.first_bank * BANK_SIZE + address] = payload[i];
    }
    return ACK;
}
```

Registration records the supplied eight-byte name, bank ownership and flags, and the bank's integrity sum in a 32-byte directory entry. The `UPLD` marker at bank offset `0x02A4` enables a registration branch that writes the integrity value at `0x02A0`. The registration sum covers offsets `0x0000-0x029F` and `0x02A8-0x3FFFF`. A separate background scan uses whole-word coverage through `0x029D` and from `0x02C0` onward. Treat the transport, registration, and background checksums as different operations. The complete bank metadata lifecycle depends on the installation and recording state.

## Ordinary phrase playback

A bank has 64 four-byte directory slots. Resolve a slot at `bank + 4 * slot`. For ordinary bank-resident playback, check the directory and the selected descriptors before emitting its first page.

| Structure | Bytes | Meaning |
| --- | --- | --- |
| Directory entry | 0-1 | Little-endian byte offset to the descriptor list, relative to the directory's base |
| | 2 | Number of four-byte descriptor words |
| | 3 | Checksum byte. The four directory bytes and all selected descriptor bytes sum to zero modulo 256. |
| Ordinary descriptor | 0-1 | Little-endian page index |
| | 2 | Number of consecutive pages |
| | 3 | Number of times to play the entire range |

A checksum failure reports `0x41` in both firmware images. The error paths also contain `0x43` for a zero descriptor count and `0x46` for an address outside the accepted playback windows. For a reference implementation, reject malformed lengths and out-of-bank references before touching memory. The C model treats all-zero or all-FF entries as inactive archive slots. The firmware can take a different branch on malformed or uninitialized bank bytes.

```c
for each descriptor in selected_phrase:
    for each repetition in 0 .. descriptor.repeats - 1:
        for each page in descriptor.range:
            emit_256_codes(page_offset(page) == 0x0d00
                           ? zero_page
                           : sample_memory_at(page));
advance_to_next_phrase_or_control_token();
```

The firmware substitutes a zero page at bank-relative `0x0D00`, even if it contains nonzero bytes. Page `0x10` has no equivalent special case in the observed page-fill routines. The firmware repeats the **whole range**, so `{page = 16, pages = 2, repeats = 2}` emits `16, 17, 16, 17`. The final page is emitted before the sequencer advances. Offline archive reconstruction must supply absent bytes according to its own policy. On a card the reader sees the current bank memory, which may hold preloaded or newly written data.

## Built-in tone playback

The sequencer uses the loaded bank's type and the requested slot to pick its directory. The table below covers successfully loaded PROM-style banks. RAM uploads also depend on runtime bank mappings.

| Loaded bank type | Firmware directory slots | Other slots |
| --- | --- | --- |
| Ordinary announcement type 0 | 0 through 3 | Bank-local page menus |
| Recognized factory announcement type 1 | 0 through 39 | Bank-local page menus from 40 |
| `TONE00AA10` or `TONE00AB10`, types 2 and 3 | 0 through 63 | Use the applicable descriptor and selected RAM address |

The loader classifies the bank from bytes `0x0670–0x067B` after loading it. For the `.bin` branch, the suffix at `0x0674` selects type 1 when it is `0AA `, `0AB `, `0BA `, or `S0CA`. The other branch recognizes the `TONE` and `U1X7` tags with `6AA0`, `6AB0`, `6BA0`, or `6CA0` for type 1 and `00AA` or `00AB` for types 2 and 3. The registration applies the type to all banks in the load. The default decoder preview uses this classification. [Load header byte layout](../FORMAT.md#load-header-and-bank-type)

Slots 0 through 3 use absolute page ranges. Slots 4 through 7 use continuous waveform records. Slots 8 through 39 have three consecutive eight-byte descriptors. Tone-service slots 40 through 63 use continuous descriptors. A leading zero word identifies the waveform-record format.

| Offset | Width | Meaning |
| --- | ---: | --- |
| 0 | 2 | Zero marker |
| 2 | 3 | Big-endian sample record address |
| 5 | 3 | Big-endian duration in units of four 16-bit words, equivalent to eight sample codes |

Slot 1 emits five copies of the 256-byte sample page at `0x400800`. Slot 2 emits 16 silent pages, three tone pages, one silent page, three tone pages, one silent page, three tone pages, and four silent pages. It gets the silent pages from `0x400700`, which startup clears. Read the counts from the ordinary built-in descriptors and replay the addressed pages. Both tested firmware builds and selectors produced identical cue codes.

A waveform record starts with a big-endian 16-bit **word count**, followed by that many two-byte sample words. In the tested finite-cycle profile, repeat the waveform record from its first sample until the duration is satisfied. Start the next descriptor immediately, including inside a staging block. Fill the unused tail of the last block with zero codes.

```c
for each finite_tone in selected_phrase:
    cycles = waveform_record(finite_tone.address);
    for (size_t i = 0; i < finite_tone.duration_quanta * 8; ++i)
        append_code(cycles[i % cycles.code_count]);
zero_pad_final_block();
advance_to_next_phrase_or_control_token();
```

The tested profile uses selector `0x4040` and runtime memory byte `[0x000001] = 1`. That byte is read by the repeat branch. With it set to zero in the harness, fixture slot 8 still filled the same number of blocks but produced different sample bytes. The actual value on a running target must be measured or recovered from the resident software. Selector `0x5050` adds `0x80000` to the first record address. Under `0x4040`, a type 2 or type 3 tone bank instead adds its physical bank offset to that address. In-buffer transitions use subsequent descriptor addresses as stored. Absolute-page cues use the same addresses under both tested selectors. Both applications derive the playback selector from `RAM[0xDEC0] & 0x87`. Values `0x81`, `0x83`, `0x85`, and `0x87` select `0x1010`, `0x2020`, `0x3030`, and `0x5050` respectively. The fallback is `0x4040`. The playback model covers the two selectors verified against the native routines. Continuous records use duration `0xFFFFFF`. When selector `0x4040` selects a type 2 or type 3 bank, the first descriptor's address is relocated by `0x40000 * bank_index`. Stream the selected record's payload cyclically across staging-block boundaries until interrupted. In both builds slot 42 uses the howler at bank offset `0x3BCA` and slot 49 uses the milliwatt at `0x379E`.

| Tone length | Descriptor value | Active codes | Nominal time |
| --- | ---: | ---: | ---: |
| Short | `0x000112` | 2,192 | 274 ms |
| Long | `0x00017C` | 3,040 | 380 ms |

All 32 combinations in each firmware reproduced the finite-cycle model byte for byte under both tested selectors. The 274/380 ms figures agree with Nortel's EDRAM table. The archive's ordinary page-based voice-file SITs are a separate playback route. [Nortel 297-1001-527, Table 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf#page=59)

## Sequencing and staging

A per-channel sequencer consumes a stream of phrase numbers, bank selects, and control tokens. The message handler stages playback or capture; the buffer service routine advances the same state for each active channel.

| Input | Observed interpretation |
| --- | --- |
| `00-3F` | Internal phrase slot. Slots 0-3 select the built-in directory. For other slots, the bank's status and type flags govern whether to use its own menu or a built-in tone route. |
| `80-9F` on ED16AA07, `80-87` on EDRMAE11 | Select a zero-based bank. The next byte must be a phrase slot. |
| `F0` | Continue parsing. |
| `F1`, `F2` | Enter capture or return to the playback-side control state. These tokens update the per-slot control word and staging direction. |
| `F3`, `F8 <byte>` | Start the timed indication path or emit a sequence status byte. |
| `F4`, `F5` | Select a built-in or bank-zero cue/silence path. |
| `F6`, `F7` | Rewind the sequence, or rewind and begin stop/drain handling. |
| `F9`, `FA` | Rewrite a rewind position or consume a queued request. |

The recovered application request handler uses byte 2 as the channel, byte 3 minus one as the number of bytes following the mode byte, and byte 4 as the mode plus flags. Its length check compares byte 0 and `(byte[3] - 1) + 5` against the supplied envelope length. The mode is `byte[4] & 0x1F`. Type `0x05` schedules a finite sequence. Type `0x02` constructs a sequence that can consume a queued request. For requests of types `0x02` and `0x05` arriving while the current mode is `0x02`, the decoder accepts one pending request and reports `0x31` when that position is occupied. Type `0x03` constructs capture descriptors for RAM banks and uses the reversed page copy in the capture states. The external message wrapping and physical recording timing still need a trace.

```c
schedule_finite(channel, flags, payload)
{
    list = empty_playlist();
    if ((flags & 0x20) == 0)
        append(list, 0xf5);
    append_bytes(list, payload);
    append(list, 0xf8, 0x00, 0xf7);
    channel.playlist = list;
    channel.mode = 0x05;
    channel.flags = 0x02;
    channel.next_state = 0x10;
}
```

| Queue frame | Generated playlist | Next state |
| --- | --- | --- |
| `07 00 01 03 25 80 09` | `80 09 F8 00 F7` | `10` |
| `07 00 01 03 05 80 09` | `F5 80 09 F8 00 F7` | `10` |
| `07 00 01 03 02 80 09` | `F8 01 F5 80 09 FA` | `10` |

The table covers an idle channel. The playback sequencer consumes the resulting list downstream of the request decoder.

For output, the interrupt-side code validates the expected half, toggles the half index, and services active channels in order. The two staging halves are separated by `0x2000` bytes. The channel mapping selects a 256-byte region and a per-channel control register. Startup primes both halves for an immediate play request. A software implementation can expose one page-ready event per channel and let the consumer choose how to clock the two buffers.

## Acceptance tests

The [measured vectors](../data/xacore/firmware/playback-vectors.json) contain exact hashes and expected events. A conforming implementation should reproduce the bytes and transitions at this boundary.

- **Repeat and silence.** Play two pages twice, a physically nonzero page 13, and one final page. Expect six blocks, with block five all zero, followed by sequence advance.
- **Archived speech or page-based tone.** Play `ESTD0AA` slot 8 using its bank-local menu. Compare the 6,912 raw staged bytes and the resulting offline A-law PCM with the archive.
- **Checksum rejection.** Change one bit of the menu checksum. Expect the native error `0x41` before staging output.
- **Protected writes.** Send packets crossing either edge of the protected window and a packet entirely inside it. Compare writable bytes, protected bytes, the sum of unfiltered payloads, and the completion reply.
- **Built-in cues.** Run slots 1 and 2 with each tested selector. Compare the ordered absolute page addresses, the output hashes, and 1,280 and 7,936 staged codes, respectively.
- **Built-in SITs.** Run slots 8-39 with each tested selector and the finite-cycle profile. Compare the active length and the full sequence of zero-padded staging blocks.

The remaining hardware acceptance cases include the resident boot handoff, live framing and interrupt timing, law and gain on the wire, RAM uploads, and service timing. DTMF records are verified in RAM. Their dispatch still needs a trace. Those cases need a card trace or the resident runtime.
