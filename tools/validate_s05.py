"""Reference-validate all corpus-s05 verifiers — every hidden test must pass
against a known-good implementation before a single model call is spent."""

import subprocess
import sys
import tempfile
from pathlib import Path

REFS = {
"bug-bound-window": '''
def sliding_max(xs, k):
    return [max(xs[i:i + k]) for i in range(len(xs) - k + 1)]
''',
"bug-bound-range": '''
def ranges_overlap(a, b):
    a0, a1 = a
    b0, b1 = b
    return a0 <= b1 and b0 <= a1
''',
"impl-bound-paginate": '''
def paginate(items, page, per_page):
    start = (page - 1) * per_page
    return list(items[start:start + per_page])
''',
"impl-bound-clamp": '''
def clamp(v, lo, hi):
    return max(lo, min(hi, v))
''',
"bug-cross-escape": '''
def encode(s):
    return s.replace("%", "%25").replace(",", "%2C")


def decode(s):
    return s.replace("%2C", ",").replace("%25", "%")
''',
"bug-cross-lexer": '''
def tokenize(expr):
    return expr.split()


def _num(t):
    try:
        return int(t)
    except ValueError:
        raise ValueError("bad token")


def evaluate(tokens):
    total = _num(tokens[0])
    i = 1
    while i < len(tokens):
        op, rhs = tokens[i], _num(tokens[i + 1])
        total = total + rhs if op == '+' else total - rhs
        i += 2
    return total


def run(expr):
    return evaluate(tokenize(expr))
''',
"impl-cross-roundtrip": '''
def _esc(s):
    return s.replace("%", "%25").replace("=", "%3D").replace(";", "%3B")


def _unesc(s):
    return s.replace("%3B", ";").replace("%3D", "=").replace("%25", "%")


def to_wire(d):
    parts = []
    for k, v in d.items():
        ek = _esc(str(k))
        if v is None:
            parts.append(ek + "=n:")
        elif isinstance(v, int):
            parts.append(ek + "=i:" + str(v))
        else:
            parts.append(ek + "=s:" + _esc(str(v)))
    return ";".join(parts)


def from_wire(s):
    if s == "":
        return {}
    out = {}
    for part in s.split(";"):
        k, tv = part.split("=", 1)
        t, _, v = tv.partition(":")
        key = _unesc(k)
        if t == "n":
            out[key] = None
        elif t == "i":
            out[key] = int(v)
        else:
            out[key] = _unesc(v)
    return out
''',
"impl-cross-pipeline": '''
def normalize(rec):
    return {k.lower(): (v.strip() if isinstance(v, str) else v)
            for k, v in rec.items()}


def validate(rec):
    errs = []
    if "name" not in rec:
        errs.append("missing name")
    if "qty" not in rec:
        errs.append("missing qty")
    elif not isinstance(rec["qty"], int) or rec["qty"] <= 0:
        errs.append("bad qty")
    return errs


def serialize(rec):
    return f"name={rec['name']};qty={rec['qty']}"


def process(rec):
    rec = normalize(rec)
    errs = validate(rec)
    return "ERR:" + errs[0] if errs else serialize(rec)
''',
"bug-state-cache": '''
import time


class TTLCache:
    def __init__(self, max_size=2, ttl=60):
        self.max_size = max_size
        self.ttl = ttl
        self._d = {}

    def _purge(self, now):
        for k in [k for k, (v, t) in self._d.items() if now - t > self.ttl]:
            del self._d[k]

    def set(self, k, v, now=None):
        now = time.time() if now is None else now
        self._purge(now)
        if len(self._d) >= self.max_size:
            oldest = min(self._d, key=lambda k: self._d[k][1])
            del self._d[oldest]
        self._d[k] = (v, now)

    def get(self, k, now=None):
        now = time.time() if now is None else now
        if k not in self._d:
            return None
        v, t = self._d[k]
        if now - t > self.ttl:
            del self._d[k]
            return None
        return v
''',
"bug-state-undo": '''
class UndoStack:
    def __init__(self):
        self._groups = []
        self._open = []

    def do(self, action):
        self._open.append(action)

    def end_group(self):
        self._groups.append(self._open)
        self._open = []

    def undo(self):
        if self._open:
            g, self._open = self._open, []
            return list(reversed(g))
        if self._groups:
            return list(reversed(self._groups.pop()))
        return []
''',
"impl-state-session": '''
class SessionCounter:
    def __init__(self):
        self._sealed = []
        self._open = 0

    def add(self, n):
        self._open += n

    def rollover(self):
        self._sealed.append(self._open)
        self._open = 0

    def total(self):
        return sum(self._sealed)

    def current(self):
        return self._open
''',
"impl-state-circuit": '''
class CircuitBreaker:
    def __init__(self, threshold=3, reset_after=30):
        self.threshold = threshold
        self.reset_after = reset_after
        self.state = "closed"
        self.streak = 0
        self.opened_at = None

    def call(self, ok, t):
        if self.state == "open":
            if t - self.opened_at >= self.reset_after:
                self.state = "half"
            else:
                return "open"
        if self.state == "half":
            if ok:
                self.state = "closed"
                self.streak = 0
                return "ok"
            self.state = "open"
            self.opened_at = t
            return "fail"
        # closed
        if ok:
            self.streak = 0
            return "ok"
        self.streak += 1
        if self.streak >= self.threshold:
            self.state = "open"
            self.opened_at = t
        return "fail"
''',
"bug-contract-sentinel": '''
MISSING = object()


def lookup(d, path, default=MISSING):
    cur = d
    for part in path.split("."):
        if part not in cur:
            if default is MISSING:
                raise KeyError(path)
            return default
        cur = cur[part]
    return cur
''',
"bug-contract-exc": '''
class OrderError(Exception):
    pass


def place_order(qty, stock):
    if not isinstance(qty, int) or qty <= 0:
        raise OrderError("qty must be a positive int")
    if qty > stock:
        raise OrderError("insufficient stock")
    return stock - qty
''',
"impl-contract-result": '''
def ok(v):
    return ("ok", v)


def err(msg):
    return ("err", msg)


def is_ok(r):
    return r[0] == "ok"


def unwrap(r):
    if r[0] == "err":
        raise RuntimeError(r[1])
    return r[1]


def map_result(r, fn):
    return ("ok", fn(r[1])) if r[0] == "ok" else r
''',
"impl-contract-iter": '''
def windowed(it, n):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) == n:
            yield tuple(buf)
            buf.pop(0)
''',
"bug-fmt-currency": '''
def money(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
''',
"bug-fmt-table": '''
def render_table(rows, widths):
    lines = []
    for row in rows:
        cells = [row[i] if i < len(row) else "" for i in range(len(widths))]
        lines.append(" | ".join(c.ljust(w) for c, w in zip(cells, widths)))
    return "\\n".join(lines)
''',
"impl-fmt-sql": '''
def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def quote_literal(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    return "'" + str(val).replace("'", "''") + "'"


def insert(table, row):
    cols = ",".join(quote_ident(c) for c in row)
    vals = ",".join(quote_literal(v) for v in row.values())
    return f'INSERT INTO {quote_ident(table)} ({cols}) VALUES ({vals})'
''',
"impl-fmt-diff": '''
def diff_lines(old, new):
    rem, add = [], []
    for i in range(max(len(old), len(new))):
        o = old[i] if i < len(old) else None
        n = new[i] if i < len(new) else None
        if o is not None and o != n:
            rem.append(o)
        if n is not None and n != o:
            add.append(n)
    out = ["-" + r for r in rem] + ["+" + a for a in add]
    return "\\n".join(out)
''',
}

ROOT = Path(__file__).resolve().parent.parent


def main():
    failures = []
    for tid, ref in REFS.items():
        d = ROOT / "eval" / "corpus-s05" / tid
        vdir = d / "verifiers"
        vfile = next(vdir.glob("test_*.py"))
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "solution.py").write_text(ref, encoding="utf-8")
            (td / vfile.name).write_text(vfile.read_text(encoding="utf-8"), encoding="utf-8")
            r = subprocess.run(
                [sys.executable, "-m", "pytest", vfile.name, "-q"],
                cwd=td, capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                failures.append(tid)
                print(f"FAIL {tid}\n{r.stdout[-800:]}\n{r.stderr[-300:]}")
            else:
                print(f"ok   {tid}")
    print(f"\n{len(REFS) - len(failures)}/{len(REFS)} verifiers pass on reference")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
