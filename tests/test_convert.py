"""Conversion and parser tests on small made-up inputs, so no firmware is needed.

Run from the repository folder: python -m unittest discover tests
"""
import os, struct, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import convert, firmware, ifrparse, model, report   # noqa: E402

G = 'EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9'


def q(prompt, offset, type_='OneOf', options=((0, 'Disabled'), (1, 'Enabled')), **kw):
    return dict(dict(var_name='Setup', var_guid=G, offset=offset, qid=offset + 1, type=type_, bits=8, prompt=prompt, form=1,
                     options=[list(o) for o in options] if type_ == 'OneOf' else [], defaults={}, min=None, max=None, step=None,
                     conds=[], help='', module='Setup'), **kw)


def bios(questions, defaults, version):
    return dict(version=version, board='E7E49AMSI', cbs_ids={},
                menus=[dict(guid='7B59104A-C00D-4158-87FF-F04D6396A915', module='Setup', title='Setup', refs=[], forms={'1': 'Main'}, varstores={'1': dict(name='Setup', guid=G, size=len(defaults))}, questions=questions)],
                defaults={('Setup', G): bytes(defaults)})


class Matching(unittest.TestCase):
    def test_inserted_setting_moves_the_rest(self):
        old = bios([q('A', 0), q('B', 1), q('C', 2)], [0, 0, 0], '2A20')
        new = bios([q('A', 0), q('New', 1), q('B', 2), q('C', 3)], [0, 0, 0, 0], '2A22')
        pairs = convert.match(convert.layout(old, 'Setup', G), convert.layout(new, 'Setup', G))
        self.assertEqual(pairs, {(0, 1): (0, 1), (1, 1): (2, 1), (2, 1): (3, 1)})

    def test_repeated_names_pair_in_order(self):
        # MSI's OC pages exist once per CPU family, with the same names at different offsets
        old = bios([q('Speed', 0), q('Speed', 1), q('Speed', 2)], [0, 0, 0], '2A20')
        new = bios([q('X', 0), q('Speed', 1), q('Speed', 2), q('Speed', 3)], [0, 0, 0, 0], '2A22')
        pairs = convert.match(convert.layout(old, 'Setup', G), convert.layout(new, 'Setup', G))
        self.assertEqual(pairs, {(0, 1): (1, 1), (1, 1): (2, 1), (2, 1): (3, 1)})


class CarryingValues(unittest.TestCase):
    SPEEDS_OLD = ((0, '6000'), (1, '6200'))
    SPEEDS_NEW = ((0, '5600'), (1, '6000'), (2, '6200'))

    def test_renumbered_option_follows_its_text(self):
        v, why = convert.carry(q('DRAM Speed', 0, options=self.SPEEDS_OLD), q('DRAM Speed', 0, options=self.SPEEDS_NEW), 1, 1)
        self.assertEqual(v, 2)
        self.assertIn('new number', why)

    def test_relabelled_option_is_kept_and_flagged(self):
        v, why = convert.carry(q('IOMMU', 0, options=((15, 'Auto'), (0, 'Disabled'))),
                               q('IOMMU', 0, options=((15, 'Compatible Mode'), (0, 'Disabled'))), 15, 1)
        self.assertEqual(v, 15)
        self.assertIn('Compatible Mode', why)

    def test_removed_option_falls_back_to_default(self):
        v, why = convert.carry(q('Mode', 0, options=((0, 'A'), (1, 'B'))), q('Mode', 0, options=((0, 'A'),)), 1, 1)
        self.assertIsNone(v)
        self.assertIn('not an option', why)

    def test_unchanged_option_has_no_note(self):
        self.assertEqual(convert.carry(q('A', 0), q('A', 0), 1, 1), (1, None))

    def test_value_the_bios_wrote_outside_the_options_is_kept(self):
        self.assertEqual(convert.carry(q('A', 0), q('A', 0), 113, 1), (113, None))

    def test_numeric_range(self):
        old = q('Volts', 0, 'Numeric', min=0, max=2000, step=1)
        self.assertIsNone(convert.carry(old, q('Volts', 0, 'Numeric', min=0, max=1000, step=1), 1500, 2)[0])
        v, why = convert.carry(old, q('Volts', 0, 'Numeric', min=0, max=20000, step=1), 1500, 2)
        self.assertEqual(v, 1500)
        self.assertIn('range changed', why)


class ConvertStore(unittest.TestCase):
    def test_rebuilt_store(self):
        old = bios([q('A', 0), q('Speed', 1, options=((0, '6000'), (1, '6200')))], [0, 0, 0x55], '2A20')
        new = bios([q('A', 0), q('New', 1), q('Speed', 2, options=((0, '5600'), (1, '6000'), (2, '6200')))], [0, 1, 0, 0x55], '2A22')
        log = []
        data, info = convert.convert_store('Setup', G, bytes([1, 1, 0x77]), old, new, lambda k, t: log.append(t))
        # A carried, New at its default, Speed moved to offset 2 and renumbered, the uncovered byte carried across
        self.assertEqual(data, bytes([1, 1, 2, 0x77]))
        self.assertEqual(info['mode'], 'rebuilt')
        self.assertEqual([n.loc for n in info['new']], [(1, 1)])
        self.assertEqual([n.loc for n in info['check']], [(2, 1)])


class Nvar(unittest.TestCase):
    @staticmethod
    def entry(body, attr):
        return b'NVAR' + struct.pack('<H', 10 + len(body)) + b'\xff\xff\xff' + bytes([attr]) + body

    def test_reads_an_entry(self):
        guid = bytes(range(16))
        buf = self.entry(b'\x00' + b'Setup\x00' + b'\x01\x02', 0x80 | 0x02)
        [(name, g, data)] = firmware.parse_nvar(buf, buf + guid)
        self.assertEqual((name, data), ('Setup', b'\x01\x02'))
        self.assertEqual(g, '03020100-0504-0706-0809-0A0B0C0D0E0F')

    def test_name_without_end_is_skipped(self):
        # A UTF-16 name with no terminator used to send the reader into an endless loop.
        buf = self.entry(b'\x00' + 'Setup'.encode('utf-16-le'), 0x80)
        self.assertEqual(firmware.parse_nvar(buf, buf + bytes(16)), [])


class IfrText(unittest.TestCase):
    def test_fields_inside_quotes_are_ignored(self):
        rest = 'Prompt: "Array Size:     ", Help: "Min: 5 is the least", QuestionId: 0x1, VarOffset: 0x15A, Size: 64, Min: 0x0'
        self.assertEqual((ifrparse.kv(rest, 'Size'), ifrparse.kv(rest, 'Min')), ('64', '0x0'))
        self.assertEqual(ifrparse.kv(rest, 'Prompt'), 'Array Size:     ')

    def test_fields_without_commas(self):
        self.assertEqual(ifrparse.kv('DefaultId: 0x0 Value: 550 { 5B 07 }', 'DefaultId'), '0x0')
        self.assertEqual(ifrparse.kv('DefaultId: 0x0 Value: 550 { 5B 07 }', 'Value'), '550')

    def test_help_lines_that_look_like_records(self):
        text = '\n'.join([
            '0x10: FormSet Guid: B863B959-0EC6-4033-99C1-8FD89F040222, Title: "T", Help: "H" { 0E }',
            f'0x20: \tVarStore Guid: {G}, VarStoreId: 0x5000, Size: 0x500, Name: "Setup" {{ 24 }}',
            '0x30: \tForm FormId: 0x1, Title: "Main" { 01 }',
            '0x40: \t\tNumeric Prompt: "Features", Help: "Specific Features',
            '0x0: Disable (default)',
            '0x40: Enable one thing',
            '** last line", QuestionFlags: 0x10, QuestionId: 0x171, VarStoreId: 0x5000, VarOffset: 0x483, Flags: 0x20, Size: 8, Min: 0x0, Max: 0xFF, Step: 0x0 { 07 }',
            '0x50: \t\t\tDefault DefaultId: 0x0 Value: 0 { 5B }',
            '0x60: \t\tEnd  { 29 }',
            '0x70: \tEnd  { 29 }',
            '0x80: End  { 29 }'])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'm.ifr.txt')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)
            [fs] = ifrparse.parse_file(p, 'M')
        [qq] = fs['questions']
        self.assertEqual((qq['offset'], qq['bits'], qq['max'], qq['defaults']), (0x483, 8, 0xFF, {'std': 0}))
        self.assertTrue(qq['help'].endswith('last line'))


class Visibility(unittest.TestCase):
    def test_constant_conditions_hide(self):
        # MSI hides pages with "SuppressIf True" and AMD with "SuppressIf <constant 1>"; Click BIOS X honours both.
        m = model.Model(bios([q('A', 0)], [0], '2A22'), {})
        f = m.fs[0]
        for tokens in ([['True']], [['Const', 1]]):
            self.assertIs(m.hidden(f, [dict(kind='SuppressIf', tokens=tokens)]), True)
        self.assertIs(m.hidden(f, [dict(kind='SuppressIf', tokens=[['Const', 0]])]), False)
        self.assertIs(m.hidden(f, [dict(kind='GrayOutIf', tokens=[['True']])]), False)     # greyed out, still on the page
        self.assertIsNone(m.hidden(f, [dict(kind='SuppressIf', tokens=[['EqIdVal', 99, 1]])]))   # value not in the file


# A small Click BIOS X: MSI's Setup formset with its menus, and two copies of AMD Overclocking (one per CPU family).
SETUP_GUID, RPL, PHX = '7B59104A-C00D-4158-87FF-F04D6396A915', '5ED15DC0-0000-0000-0000-000000000001', '5ED15DC0-0000-0000-0000-000000000002'
CBS = '3A997502-647A-4C82-998E-52EF9486A247'


def ref(src, dst, prompt, dst_fs=None):
    return dict(src=src, dst=dst, dst_fs=dst_fs, prompt=prompt, conds=[])


def click_bios_x(forms=None):
    forms = forms or {'1': 'Setup', '2': 'Settings', '3': 'System Status', '4': 'Advanced', '5': 'Boot', '6': 'Overclocking',
                      '7': 'Security', '8': 'Hardware Monitor', '9': 'Integrated Peripherals', '10': 'CPU Fan 1'}
    setup = dict(guid=SETUP_GUID, module='Setup', title='Setup', forms=forms,
                 varstores={'1': dict(name='Setup', guid=G, size=16)},
                 refs=[ref(2, 3, 'System Status'), ref(2, 4, 'Advanced'), ref(2, 5, 'Boot'), ref(4, 9, 'Integrated Peripherals'),
                       ref(8, 10, 'CPU Fan 1')],
                 questions=[q('Boot Mode', 0, form=5), q('LAN', 1, form=9), q('ErP', 2, form=4), q('CPU Ratio', 3, form=6),
                            q('Fan Mode', 4, form=10), q('Date Format', 5, form=3), q('TPM', 6, form=7)])
    aod = [dict(guid=g, module='AodDxe', title='AMD Overclocking', forms={'1': 'AMD Overclocking'}, refs=[],
                varstores={'1': dict(name=n, guid=g, size=4)}, questions=[q('PBO', 0, var_name=n, var_guid=g, module='AodDxe')])
           for n, g in (('AodSetupRpl', RPL), ('AodSetupPhx', PHX))]
    return dict(version='2A22', board='E7E49AMSI', cbs_ids={}, menus=[setup] + aod, defaults={('Setup', G): bytes(16)})


class Menus(unittest.TestCase):
    def test_paths_and_order(self):
        rows = model.decode(click_bios_x(), {('Setup', G): bytes(16), ('AodSetupRpl', RPL): bytes(4)})
        got = [(model.path_s(r), r['prompt']) for r in sorted(rows, key=model.sort_key)]
        self.assertEqual(got, [('System Status', 'Date Format'),
                               ('Advanced', 'ErP'),
                               ('Advanced > Integrated Peripherals', 'LAN'),
                               ('Advanced > AMD Overclocking', 'PBO'),       # AMD Overclocking comes last in Advanced
                               ('Overclocking', 'CPU Ratio'),
                               ('Security', 'TPM'),
                               ('Boot', 'Boot Mode'),
                               ('Hardware Monitor > CPU Fan 1', 'Fan Mode'),
                               (None, 'PBO')])                              # the other CPU family's copy
        self.assertEqual(model.layout_problems(click_bios_x()), [])

    def test_one_amd_overclocking_when_a_read_holds_every_family(self):
        cur = {('Setup', G): bytes(16), ('AodSetupRpl', RPL): bytes(4), ('AodSetupPhx', PHX): bytes(4),
               ('AmdSetupRPL', CBS): b'\x25\xbf\xe4\xd1' + bytes(12), ('AmdSetupPHX', CBS): bytes(16)}
        rows = model.decode(click_bios_x(), cur)
        pbo = [r for r in rows if r['prompt'] == 'PBO']
        self.assertEqual([(r['store'], r['reach'], r['other_cpu']) for r in sorted(pbo, key=lambda r: r['store'])],
                         [('AodSetupPhx', False, True), ('AodSetupRpl', True, False)])

    def test_missing_menus_are_reported(self):
        renamed = click_bios_x({'1': 'Setup', '2': 'Main Settings', '6': 'Overclocking', '7': 'Security', '8': 'Hardware Monitor'})
        [t] = model.layout_problems(renamed)
        self.assertIn('System Status, Advanced and Boot menus', t)
        renamed['unread'] = ['AodDxe']
        self.assertIn('AodDxe', model.layout_problems(renamed)[1])


class Values(unittest.TestCase):
    def test_msi_formats(self):
        num = lambda prompt='X', **kw: q(prompt, 0, 'Numeric', **kw)
        self.assertEqual(model.fmt(num(bits=16), 0), 'Auto')                      # MSI's wide settings show 0 as Auto
        self.assertEqual(model.fmt(num(), 0), '0')
        self.assertEqual(model.fmt(num(bits=16, help='Range: 8~255 T'), 60), '60 T')
        self.assertEqual(model.fmt(num(prompt='CPU Core Voltage', bits=16, max=2000), 1250), '1.250 V (1250 mV)')
        self.assertEqual(model.fmt(num(prompt='SOC Voltage', var_name='AmdSetupRPL', bits=16), 0), '0')


class Report(unittest.TestCase):
    def test_placeholders_in_names_are_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'r.html')
            report.write_html(out, [], title='a __DATA__ b', eyebrow='__INTRO__', meta=['__TITLE__'], intro=['x'])
            with open(out, encoding='utf-8') as f:
                page = f.read()
        self.assertIn('<title>a __DATA__ b</title>', page)
        self.assertIn('<div class="eyebrow">__INTRO__</div>', page)
        self.assertEqual(page.count('const DATA = {'), 1)


if __name__ == '__main__':
    unittest.main()
