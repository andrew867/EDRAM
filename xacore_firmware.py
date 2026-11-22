"""Convert the two Nortel firmware loads into flat binaries and mapped m68k ELF files."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import edram


def elf_image(image, layout):
    # One program header and one named section per assigned region.
    name_table = bytearray(b'\0')
    program_headers = []
    section_headers = [bytes(40)]
    body = bytearray(52 + 32 * len(layout))
    for name, start, stop, executable in layout:
        while len(body) % 2:
            body.append(0)
        offset = len(body)
        data = image.read_bytes(start, stop - start)
        body.extend(data)
        program_headers.append(struct.pack(
            '>8I', 1, offset, start, start, len(data), len(data), 5 if executable else 4, 1
        ))
        name_offset = len(name_table)
        name_table.extend(name.encode('ascii') + b'\0')
        section_headers.append(struct.pack(
            '>10I', name_offset, 1, 6 if executable else 2, start, offset, len(data), 0, 0, 2, 0
        ))
    name_offset = len(name_table)
    name_table.extend(b'.shstrtab\0')
    section_headers.append(struct.pack(
        '>10I', name_offset, 3, 0, 0, len(body), len(name_table), 0, 0, 1, 0
    ))
    body.extend(name_table)
    while len(body) % 4:
        body.append(0)
    section_offset = len(body)
    body.extend(b''.join(section_headers))
    ident = b'\x7fELF\x01\x02\x01' + bytes(9)
    body[:52] = struct.pack(
        '>16sHHIIIIIHHHHHH', ident, 2, 4, 1, 0x412, 52, section_offset, 0,
        52, 32, len(program_headers), 40, len(section_headers), len(section_headers) - 1
    )
    body[52:52 + 32 * len(program_headers)] = b''.join(program_headers)
    return bytes(body)


def convert(path, output):
    source = path.read_bytes()
    records = edram.parse_srec(source)
    if any(record.kind != 'S2' for record in records):
        raise ValueError(f'Unexpected record type in {path}')
    image = edram.Image(records, strict_overlaps=True)
    addressed = sum(image.coverage)
    if addressed != sum(len(record.data) for record in records):
        raise ValueError(f'Overlapping S2 records in {path}')
    runs = [(item.start(), item.end()) for item in re.finditer(b'\x01+', image.coverage)]
    base, end = runs[0][0], runs[-1][1]
    layout = [
        ('.low_descriptor', 0x400, 0x406, False),
        ('.entry_stubs', 0x412, 0x41e, True),
        ('.load_descriptor', 0x45a, 0x47a, False),
        ('.exec_header', 0xe800, 0xe900, False),
        ('.exec_code', 0xe900, 0x10f3a, True),
        ('.app_code_and_data', 0x11400, max(end for start, end in runs if end < 0x1b600), True),
        ('.sample_table_a', 0x1b600, 0x1bf56, False),
        ('.sample_table_b', 0x1c000, 0x1c956, False),
    ]
    if any(not any(low <= a and b <= high for _,low,high,_ in layout)
           for a,b in runs if not (a < 0xe900 < b)):
        raise ValueError(f'Unmapped S2 range in {path}')
    if any(not any(low <= addr < high for _, low, high, _ in layout)
           for a, b in runs for addr in range(a, b)):
        raise ValueError(f'Incomplete ELF mapping in {path}')

    flat_name = path.stem + '.base-000400.bin'
    flat = bytes(image.data[base:end])
    (output / flat_name).write_bytes(flat)
    elf_name = path.stem + '.m68k.elf'
    elf = elf_image(image, layout)
    (output / elf_name).write_bytes(elf)
    # Independently read back emitted program headers before releasing each pair.
    ehsize, phsize, phnum = struct.unpack_from('>HHH', elf, 40)
    addresses = {}
    for idx in range(phnum):
        _, offset, addr, _, length, _, _, _ = struct.unpack_from('>8I', elf, ehsize + idx * phsize)
        addresses.update(enumerate(elf[offset:offset + length], addr))
    for record in records:
        assert flat[record.address-base:record.address-base+len(record.data)] == record.data
        assert bytes(addresses[record.address+i] for i in range(len(record.data))) == record.data
    last = source.decode('ascii').splitlines()[-1]
    assert last.startswith('S6') and len(last) == 14
    stubs = {}
    for stub in (0x412, 0x418):
        op, target = struct.unpack('>HI', image.read_bytes(stub, 6, required=True))
        assert op == 0x4ef9 and image.coverage[target]
        stubs[f'0x{stub:06x}'] = f'0x{target:06x}'
    result = {
        'source': path.name, 's2_records': len(records), 'addressed_bytes': addressed,
        'flat_binary': flat_name, 'flat_sha256': hashlib.sha256(flat).hexdigest(),
        'flat_load_address': f'0x{base:06x}', 'end_exclusive': f'0x{end:06x}',
        'unaddressed_fill': '00', 'm68k_elf': elf_name, 'elf_sha256': hashlib.sha256(elf).hexdigest(),
        'synthetic_elf_entry': '0x000412', 'observed_absolute_jumps': stubs,
        'nortel_s6_footer': last,
        'exact_ranges_half_open': [[f'0x{a:06x}', f'0x{b:06x}'] for a,b in runs],
        'elf_regions_half_open': [[name, f'0x{a:06x}', f'0x{b:06x}', 'RX' if executable else 'R']
                                  for name,a,b,executable in layout],
    }
    print(path.stem, len(records), addressed, stubs, last, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Directory containing the two extracted S-record files')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = [convert(args.source / f'{name}.srec', args.output) for name in ('ED16AA07','EDRMAE11')]
    (args.output / 'address-map.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
