"""Profile format tests on a small made-up profile, so no firmware or real settings are needed.

Run from the repository folder: python -m unittest discover tests
"""
import os, struct, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import ocb   # noqa: E402


def make_profile(version=b'2A22', entries=((0, 0x417276EE, 7, b'\x01\x00\x02\x03'), (1, 0x1234, 7, b''), (5, 0xFFFCC9C3, 7, b'en-US\x00'))):
    head = b'$MOS$E7E49AMSI.' + version
    body = b''.join(struct.pack('<IIIH', i, id_, attr, len(d)) + d for i, id_, attr, d in entries)
    cmos = bytes(range(256))
    oci = (b'$OCI$\x00E7E49AMSI\x00' + version + b'\x00Test CPU        \x0020261018095931\x00'
           + struct.pack('<IIII', 10000, 43, 1348, 6200) + b'\x00' * 16)
    raw = bytearray(head + b'\x00\x00\x00\x00' + struct.pack('<I', len(entries)) + body + cmos + oci)
    struct.pack_into('<I', raw, len(head), ocb.checksum(raw, len(head)))
    return bytes(raw)


class ProfileFormat(unittest.TestCase):
    def test_reads_header_entries_and_info(self):
        p = ocb.Profile(make_profile())
        self.assertEqual((p.board, p.version), ('E7E49AMSI', '2A22'))
        self.assertTrue(p.checksum_ok)
        self.assertEqual([e.index for e in p.entries], [0, 1, 5])
        self.assertEqual(p.entries[0].data, b'\x01\x00\x02\x03')
        self.assertEqual(p.entries[1].data, b'')
        self.assertEqual((p.cpu, p.saved, p.oci_version), ('Test CPU', '2026-10-18 09:59', '2A22'))

    def test_checksum_definition(self):
        raw = make_profile()
        stored, = struct.unpack_from('<I', raw, 0x13)
        rest = sum(raw) - sum(raw[0x13:0x17])
        self.assertEqual((rest + stored) & 0xFFFFFFFF, 0)

    def test_build_unchanged_is_identical(self):
        raw = make_profile()
        self.assertEqual(ocb.Profile(raw).build(), raw)

    def test_relabel_changes_only_versions_and_checksum(self):
        raw = make_profile()
        out = ocb.Profile(raw).build(version='2A25')
        p = ocb.Profile(out)
        self.assertTrue(p.checksum_ok)
        self.assertEqual((p.version, p.oci_version), ('2A25', '2A25'))
        # identical to a profile made for 2A25 in the first place
        self.assertEqual(out, make_profile(version=b'2A25'))

    def test_damaged_checksum_is_reported(self):
        raw = bytearray(make_profile()); raw[0x30] ^= 0xFF
        self.assertFalse(ocb.Profile(bytes(raw)).checksum_ok)

    def test_not_a_profile(self):
        with self.assertRaises(ocb.ProfileError):
            ocb.Profile(b'PK\x03\x04' + bytes(100))

    def test_truncated_profile(self):
        with self.assertRaises(ocb.ProfileError):
            ocb.Profile(make_profile()[:0x25])

    def test_cut_inside_the_header(self):
        with self.assertRaises(ocb.ProfileError):
            ocb.Profile(make_profile()[:0x15])


if __name__ == '__main__':
    unittest.main()
