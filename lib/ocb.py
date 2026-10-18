"""Read and write MSI Click BIOS OC profiles (.ocb).

Layout, as found on the MS-7E49 (2.A20, 2.A22):
  '$MOS$' + board id + '.' + 4-character BIOS version   e.g. '$MOS$E7E49AMSI.2A22'
  u32 checksum      = -(sum of every other byte in the file) mod 2^32
  u32 entry count
  entries           <u32 index><u32 id><u32 attributes><u16 size><data>
  tail              256-byte copy of CMOS, then a '$OCI$' block with board id,
                    version, CPU name and save time (yyyymmddhhmmss)
"""
import struct

MAGIC = b'$MOS$'


class ProfileError(Exception):
    pass


def label(v):
    """'2A25' -> '2.A25', the way MSI writes BIOS versions."""
    return f'{v[0]}.{v[1:]}' if len(v) == 4 else v


def checksum(data, chk_off):
    return (-(sum(data) - sum(data[chk_off:chk_off + 4]))) & 0xFFFFFFFF


class Entry:
    __slots__ = ('index', 'id', 'attr', 'data')

    def __init__(self, index, id_, attr, data):
        self.index, self.id, self.attr, self.data = index, id_, attr, bytes(data)


class Profile:
    def __init__(self, raw):
        self.raw = bytes(raw)
        if not raw.startswith(MAGIC):
            raise ProfileError('Not an MSI OC profile: the file does not start with $MOS$.')
        dot = raw.find(b'.', len(MAGIC), 40)
        if dot < 0:
            raise ProfileError('Unexpected profile header: no BIOS version found.')
        self.board = raw[len(MAGIC):dot].decode('ascii', 'replace')
        self.ver_off = dot + 1
        self.version = raw[self.ver_off:self.ver_off + 4].decode('ascii', 'replace')
        self.chk_off = self.ver_off + 4
        if len(raw) < self.chk_off + 8:
            raise ProfileError('The profile is cut short: it ends inside the header.')
        self.stored_checksum, count = struct.unpack_from('<II', raw, self.chk_off)
        self.checksum_ok = self.stored_checksum == checksum(raw, self.chk_off)
        pos = self.chk_off + 8
        self.entries = []
        while len(self.entries) < count:
            if pos + 14 > len(raw):
                raise ProfileError(f'Profile ends after {len(self.entries)} of {count} entries.')
            idx, id_, attr, size = struct.unpack_from('<IIIH', raw, pos)
            if attr > 0xFF or pos + 14 + size > len(raw):
                raise ProfileError(f'Entry {len(self.entries)} at {pos:#x} does not look valid; the format may have changed.')
            self.entries.append(Entry(idx, id_, attr, raw[pos + 14:pos + 14 + size]))
            pos += 14 + size
        self.tail = raw[pos:]
        oci = self.tail.find(b'$OCI$\x00')
        if oci < 0:
            raise ProfileError('No $OCI$ information block at the end of the profile.')
        parts = self.tail[oci + 6:].split(b'\x00')
        self.oci_board = parts[0].decode('ascii', 'replace') if parts else ''
        self.oci_version = parts[1].decode('ascii', 'replace') if len(parts) > 1 else ''
        self.cpu = parts[2].decode('ascii', 'replace').strip() if len(parts) > 2 else ''
        ts = parts[3].decode('ascii', 'replace') if len(parts) > 3 else ''
        self.saved = f'{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}' if len(ts) == 14 and ts.isdigit() else ts

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls(f.read())

    def build(self, version=None):
        """Bytes of the profile with the current entries; optionally re-labelled to another BIOS version."""
        version = (version or self.version).encode('ascii')
        if len(version) != 4:
            raise ProfileError('BIOS version must be 4 characters, e.g. 2A25.')
        head = bytearray(self.raw[:self.chk_off])
        head[self.ver_off:self.ver_off + 4] = version
        body = bytearray()
        for e in self.entries:
            body += struct.pack('<IIIH', e.index, e.id, e.attr, len(e.data)) + e.data
        tail = bytearray(self.tail)
        old = b'$OCI$\x00' + self.oci_board.encode() + b'\x00' + self.oci_version.encode() + b'\x00'
        at = tail.find(old)
        if at < 0:
            raise ProfileError('Could not find the version in the $OCI$ block.')
        tail[at:at + len(old)] = b'$OCI$\x00' + self.oci_board.encode() + b'\x00' + version + b'\x00'
        out = head + b'\x00' * 4 + struct.pack('<I', len(self.entries)) + body + tail
        struct.pack_into('<I', out, self.chk_off, checksum(out, self.chk_off))
        return bytes(out)


def describe(p):
    used = [e for e in p.entries if e.data]
    return (f'Board {p.board}, BIOS {p.version}, saved {p.saved}, CPU {p.cpu or "?"}\n'
            f'Checksum {p.stored_checksum:#010x} ({"valid" if p.checksum_ok else "DOES NOT MATCH"}), '
            f'{len(p.entries)} entries, {len(used)} with data, {sum(len(e.data) for e in used)} bytes of settings')
