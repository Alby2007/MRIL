"""Reference-validate all Study 04 verifiers — every hidden test must pass
against a known-good implementation before a single model call is spent."""

import subprocess
import sys
import tempfile
from pathlib import Path

REFS = {
"bug-tmpl-repeat": '''
def render(template, values):
    for k, v in values.items():
        template = template.replace('{' + k + '}', str(v))
    return template
''',
"bug-tmpl-escape": '''
def render(template, values):
    out, i = '', 0
    while i < len(template):
        if template[i:i+2] == '{{': out += '{'; i += 2
        elif template[i:i+2] == '}}': out += '}'; i += 2
        elif template[i] == '{':
            j = template.find('}', i)
            key = template[i+1:j]
            out += str(values[key]) if key in values else template[i:j+1]
            i = j + 1
        else: out += template[i]; i += 1
    return out
''',
"impl-tmpl-basic": '''
def render(template, values):
    out, i = '', 0
    while i < len(template):
        if template[i] == '{':
            j = template.find('}', i)
            if j == -1: out += template[i]; i += 1; continue
            key = template[i+1:j]
            out += str(values[key]) if key in values else template[i:j+1]
            i = j + 1
        else: out += template[i]; i += 1
    return out
''',
"impl-tmpl-strict": '''
def render(template, values):
    out, i = '', 0
    while i < len(template):
        if template[i:i+2] == '{{': out += '{'; i += 2
        elif template[i:i+2] == '}}': out += '}'; i += 2
        elif template[i] == '{':
            j = template.find('}', i)
            field = template[i+1:j]
            if ':' in field: key, spec = field.split(':', 1)
            else: key, spec = field, ''
            if key not in values: i = j + 1; continue
            v = str(values[key])
            out += f'{v:{spec}}' if spec else v
            i = j + 1
        else: out += template[i]; i += 1
    return out
''',
"bug-dt-between": '''
def days_between(a, b):
    return abs((b - a).days)
''',
"bug-dt-months": '''
import calendar
from datetime import date
def add_months(d, n):
    m0 = (d.year * 12 + d.month - 1) + n
    y, m = divmod(m0, 12)
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)
''',
"impl-dt-weekday": '''
def weekday_name(d):
    return d.strftime('%A')
''',
"impl-dt-business": '''
from datetime import date, timedelta
def business_days(start, end, holidays):
    try:
        s = date.fromisoformat(start); e = date.fromisoformat(end)
        hol = {date.fromisoformat(h) for h in holidays}
    except ValueError:
        raise
    def count(a, b):
        n, d = 0, a
        while d < b:
            if d.weekday() < 5 and d not in hol: n += 1
            d += timedelta(days=1)
        return n
    if s <= e: return count(s, e)
    return -count(e, s)
''',
"bug-regex-pairs": '''
import re
def pairs(text):
    return re.findall(r'(\\w+)=(\\w+)', text)
''',
"bug-regex-loglines": '''
import re
def count_errors(text):
    return len(re.findall(r'^ERROR', text, re.M))
''',
"impl-regex-slug": '''
import re
def slugify(text):
    t = re.sub(r'[ _]+', '-', text.lower())
    t = re.sub(r'[^a-z0-9-]', '', t)
    t = re.sub(r'-+', '-', t)
    return t.strip('-')
''',
"impl-regex-logparse": '''
import re
def parse_log_line(line):
    m = re.match(r'^\\[(DEBUG|INFO|WARN|ERROR)\\]\\s+(.*?)\\s+\\(code\\s+(\\d+)\\)\\s*$', line)
    if not m: return None
    return {'level': m.group(1), 'message': m.group(2), 'code': int(m.group(3))}
''',
"bug-multi-shared": '''
_items = []
def add(item):
    _items.append(item)
def total():
    return sum(_items)
''',
"bug-multi-counter": '''
class WordCounter:
    def __init__(self):
        self._counts = {}
    def add(self, word):
        self._counts[word] = self._counts.get(word, 0) + 1
    def top(self):
        return max(self._counts, key=self._counts.get) if self._counts else None
''',
"impl-multi-stack": '''
_stack = []
def push(v): _stack.append(v)
def pop():
    if not _stack: raise IndexError('pop on empty stack')
    return _stack.pop()
def apply(op):
    need = 1 if op == 'neg' else 2
    if len(_stack) < need: raise IndexError('not enough operands')
    if op == 'neg': _stack.append(-_stack.pop())
    else:
        b, a = _stack.pop(), _stack.pop()
        _stack.append({'add': a+b, 'sub': a-b, 'mul': a*b}[op])
''',
"impl-multi-undo": '''
class TextBuffer:
    def __init__(self):
        self._buf = ''
        self._ops = []
    def write(self, text):
        self._buf += text; self._ops.append(('w', text))
    def delete(self, n):
        removed = self._buf[-n:] if n <= len(self._buf) else self._buf
        self._buf = self._buf[:-n] if n <= len(self._buf) else ''
        self._ops.append(('d', removed))
    def undo(self):
        if not self._ops: return
        kind, payload = self._ops.pop()
        if kind == 'w': self._buf = self._buf[:-len(payload)] if payload else self._buf
        else: self._buf += payload
    def contents(self): return self._buf
''',
"bug-serde-fields": '''
class Person:
    def __init__(self, name, age, city):
        self.name, self.age, self.city = name, age, city
    def __eq__(self, other):
        return (self.name, self.age, self.city) == (other.name, other.age, other.city)
def person_to_dict(p):
    return {'name': p.name, 'age': p.age, 'city': p.city}
def dict_to_person(d):
    return Person(d['name'], d['age'], d['city'])
''',
"bug-serde-nested": '''
class Item:
    def __init__(self, sku, qty):
        self.sku, self.qty = sku, qty
    def __eq__(self, other):
        return (self.sku, self.qty) == (other.sku, other.qty)
class Order:
    def __init__(self, items, note=None):
        self.items, self.note = items, note
    def __eq__(self, other):
        return self.items == other.items and self.note == other.note
def order_to_dict(o):
    d = {'items': [{'sku': i.sku, 'qty': i.qty} for i in o.items]}
    if o.note is not None: d['note'] = o.note
    return d
def dict_to_order(d):
    return Order([Item(i['sku'], i['qty']) for i in d['items']], note=d.get('note'))
''',
"impl-serde-basic": '''
class Product:
    def __init__(self, name, price, tags):
        self.name, self.price, self.tags = name, price, tags
    def __eq__(self, other):
        return (self.name, self.price, self.tags) == (other.name, other.price, other.tags)
def product_to_dict(p):
    return {'name': p.name, 'price': p.price, 'tags': list(p.tags)}
def dict_to_product(d):
    return Product(d['name'], d['price'], list(d['tags']))
''',
"impl-serde-versioned": '''
class Entry:
    def __init__(self, sku, qty, note=None):
        self.sku, self.qty, self.note = sku, qty, note
def serialize(e):
    d = {'v': 2, 'sku': e.sku, 'qty': int(e.qty)}
    if e.note is not None: d['note'] = e.note
    return d
def deserialize(d):
    allowed = {'v', 'sku', 'qty', 'note'}
    if set(d) - allowed: raise ValueError('unknown keys')
    return Entry(d['sku'], int(d['qty']), note=d.get('note'))
''',
"bug-validate-age": '''
def check_user(d):
    if not isinstance(d.get('name'), str) or not d['name'].strip():
        raise ValueError('name required')
    if d.get('age', 0) < 0:
        raise ValueError('bad age')
    return True
''',
"bug-validate-order": '''
_ALLOWED = {'new', 'paid', 'shipped'}
def validate_order(quantity, price, status):
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError('bad quantity')
    if price < 0:
        raise ValueError('bad price')
    if status not in _ALLOWED:
        raise ValueError('bad status')
    return True
''',
"impl-validate-form": '''
class FormValidator:
    def __init__(self, fields):
        self._fields = fields; self._required = []
    def require(self, name):
        self._required.append(name)
    def is_valid(self):
        return not self.errors
    @property
    def errors(self):
        return [n for n in self._required
                if n not in self._fields or not str(self._fields[n]).strip()]
''',
"impl-validate-request": '''
class RequestValidator:
    def __init__(self, spec):
        self._spec = spec; self._errors = []
    def validate(self, payload):
        self._errors = []
        for name, (req, typ, lo, hi) in self._spec.items():
            if name not in payload:
                if req == 'required': self._errors.append(f'missing:{name}')
                continue
            v = payload[name]
            if not isinstance(v, typ): self._errors.append(f'type:{name}'); continue
            if lo is not None and v < lo: self._errors.append(f'range:{name}')
            elif hi is not None and v > hi: self._errors.append(f'range:{name}')
        for k in payload:
            if k not in self._spec: self._errors.append(f'unknown:{k}')
        return not self._errors
    @property
    def errors(self): return self._errors
''',
}


def main():
    root = Path("eval/corpus-s04")
    failures = 0
    for tid, ref in REFS.items():
        tdir = root / tid
        tests = sorted((tdir / "verifiers").glob("*.py"))
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "solution.py").write_text(ref)
            for tf in tests:
                (td / tf.name).write_bytes(tf.read_bytes())
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"] + [t.name for t in tests],
                cwd=td, capture_output=True, text=True)
            ok = r.returncode == 0
            print(f"{tid:26s} {'PASS' if ok else 'FAIL'}")
            if not ok:
                failures += 1
                print(r.stdout[-700:])
    print(f"\n{len(REFS) - failures}/{len(REFS)} verifiers pass on reference")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
