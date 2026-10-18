"""IFR text (IFRExtractor-RS verbose output) -> formsets with forms, refs, questions and their SuppressIf/GrayOutIf/DisableIf expressions."""
import re, os, glob

LINE = re.compile(r'^0x([0-9A-F]+):\s(\t*)(\w+)\s?(.*)$', re.S)
RAW = re.compile(r'\{ ([0-9A-F ]+) \}\s*$')
EXPR = {'EqIdVal', 'EqIdValList', 'EqIdId', 'QuestionRef1', 'Uint8', 'Uint16', 'Uint32', 'Uint64', 'True', 'False',
        'Not', 'And', 'Or', 'Equal', 'NotEqual', 'LessThan', 'LessEqual', 'GreaterThan', 'GreaterEqual'}
CONDS = {'SuppressIf', 'GrayOutIf', 'DisableIf'}
QUOTE = re.compile(r'(?<!\\)"')

FIELD = re.compile(r'(\w+): ("(?:[^"\\]|\\.)*"|[^,{\s]*)')


def kv(s, key):
    """Value of 'Key: value' or 'Key: "text"' in an IFRExtractor line. Fields are read left to right, so a word
    inside a prompt or help text (a RAID prompt reads "Array Size:") is never taken for a field."""
    for m in FIELD.finditer(s):
        if m.group(1) == key:
            v = m.group(2)
            return v[1:-1] if v.startswith('"') else (v or None)
    return None

def num(x):
    if x is None: return None
    x = x.strip()
    try: return int(x, 16) if x.lower().startswith('0x') else int(x)
    except ValueError: return None

def token(op, rest):
    if op == 'EqIdVal': return [op, num(kv(rest, 'QuestionId')), num(kv(rest, 'Value'))]
    if op == 'EqIdValList':
        m = re.search(r'Values: \[([^\]]*)\]', rest)
        return [op, num(kv(rest, 'QuestionId')), [num(x) for x in m.group(1).split(',')] if m else []]
    if op == 'EqIdId': return [op, num(kv(rest, 'QuestionId')), num(kv(rest, 'OtherQuestionId'))]
    if op == 'QuestionRef1': return [op, num(kv(rest, 'QuestionId'))]
    if op.startswith('Uint'): return ['Const', num(kv(rest, 'Value'))]
    return [op]

def parse_file(path, module):
    formsets, fs = [], None
    cond = []                   # stack of dict(depth, kind, tokens, collecting)
    cur_form, cur_q = None, None
    with open(path, encoding='utf-8', errors='replace') as f:
        raw_lines = f.read().split('\n')
    joined = []
    for l in raw_lines:
        # Help and prompt text can run over several lines, and a continuation line can itself start with "0x40: ".
        # A line belongs to the one before while that one has a quote left open.
        if joined and (len(QUOTE.findall(joined[-1])) % 2 or not re.match(r'^0x[0-9A-F]+: ', l)): joined[-1] += '\n' + l
        else: joined.append(l)
    for line in joined:
        m = LINE.match(line)
        if not m: continue
        off, tabs, op, rest = m.groups()
        depth = len(tabs)
        raw = RAW.search(rest)
        rawb = [int(b, 16) for b in raw.group(1).split()] if raw else []
        if op == 'FormSet':
            fs = dict(module=module, guid=kv(rest, 'Guid'), title=kv(rest, 'Title'), varstores={}, forms={}, refs=[], questions=[])
            formsets.append(fs); cur_form = None; cond = []; cur_q = None
            continue
        if fs is None: continue
        # expression collection for the innermost condition
        if cond and cond[-1]['collecting']:
            if op in EXPR:
                cond[-1]['tokens'].append(token(op, rest)); continue
            if op == 'End' and depth > cond[-1]['depth']:
                continue                          # end of an expression sub-scope
            cond[-1]['collecting'] = False
        if op in CONDS:
            cond.append(dict(depth=depth, kind=op, tokens=[], collecting=True)); continue
        if op == 'End':
            while cond and cond[-1]['depth'] >= depth: cond.pop()
            if cur_q is not None and depth <= cur_q['_depth']: cur_q = None
            continue
        active = [dict(kind=c['kind'], tokens=c['tokens']) for c in cond]
        if op in ('VarStore', 'VarStoreEfi'):
            fs['varstores'][num(kv(rest, 'VarStoreId'))] = dict(guid=kv(rest, 'Guid'), name=kv(rest, 'Name'), size=num(kv(rest, 'Size')))
        elif op == 'Form':
            cur_form = num(kv(rest, 'FormId')); fs['forms'][cur_form] = kv(rest, 'Title'); cond = []
        elif op == 'Ref':
            fid = num(kv(rest, 'FormId'))
            if cur_form is not None and fid is not None:
                fs['refs'].append(dict(src=cur_form, dst=fid, dst_fs=kv(rest, 'FormSetGuid'), prompt=kv(rest, 'Prompt'), conds=active))
        elif op in ('OneOf', 'CheckBox', 'Numeric', 'String'):
            q = dict(module=module, form=cur_form, type=op, prompt=kv(rest, 'Prompt'), help=kv(rest, 'Help'),
                     qid=num(kv(rest, 'QuestionId')), vsid=num(kv(rest, 'VarStoreId')), offset=num(kv(rest, 'VarOffset')),
                     flags=num(kv(rest, 'Flags')), conds=active, options=[], defaults={}, _depth=depth)
            if op == 'CheckBox':
                q['bits'] = 8
                d = kv(rest, 'Default'); md = kv(rest, 'MfgDefault')
                if d: q['defaults']['std'] = 1 if d == 'Enabled' else 0
                if md: q['defaults']['mfg'] = 1 if md == 'Enabled' else 0
            elif op in ('OneOf', 'Numeric'):
                q['bits'] = num(kv(rest, 'Size'))
                q['min'], q['max'], q['step'] = num(kv(rest, 'Min')), num(kv(rest, 'Max')), num(kv(rest, 'Step'))
                q['display_hex'] = op == 'Numeric' and bool((q['flags'] or 0) & 0x20)
            fs['questions'].append(q); cur_q = q
        elif op == 'OneOfOption' and cur_q is not None:
            val = num(kv(rest, 'Value')); oflags = rawb[4] if len(rawb) > 4 else 0
            cur_q['options'].append((val, kv(rest, 'Option')))
            if oflags & 0x10: cur_q['defaults'].setdefault('opt_std', val)
        elif op == 'Default' and cur_q is not None:
            did = num(kv(rest, 'DefaultId')); val = num(kv(rest, 'Value'))
            if val is not None and did is not None:
                cur_q['defaults'].setdefault('std' if did == 0 else ('mfg' if did == 1 else 'id%d' % did), val)
    for fs in formsets:
        for q in fs['questions']:
            q.pop('_depth', None)
            vs = fs['varstores'].get(q['vsid'])
            q['var_name'], q['var_guid'] = (vs['name'], vs['guid']) if vs else (None, None)
        fs['varstores'] = {str(k): v for k, v in fs['varstores'].items()}
        fs['forms'] = {str(k): v for k, v in fs['forms'].items()}
    return formsets

def parse_dir(ifrdir):
    score = {}
    for p in glob.glob(os.path.join(ifrdir, '*.ifr.txt')):
        base = os.path.basename(p); module = base.split('.efi')[0]
        mm = re.search(r'\.efi\.(\d+)\.(\d+)\.', base)
        if not mm: continue
        with open(p, encoding='utf-8', errors='replace') as f:
            t = f.read()
        bad = t.count('InvalidId') * 5 + len(re.findall(r'Option: "[^"]{70,}"', t)) * 3 + t.count('Prompt: ""')
        score.setdefault((module, mm.group(1)), []).append((bad, mm.group(2)))
    best = {k: min(v)[1] for k, v in score.items()}
    allfs = []
    for p in sorted(glob.glob(os.path.join(ifrdir, '*.ifr.txt'))):
        base = os.path.basename(p); module = base.split('.efi')[0]
        mm = re.search(r'\.efi\.(\d+)\.(\d+)\.', base)
        if mm and best.get((module, mm.group(1))) != mm.group(2): continue
        allfs += parse_file(p, module)
    return allfs
