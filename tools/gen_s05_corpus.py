"""Generate corpus-s05: 20 fresh tasks across five failure-mechanism
families. Frozen for Study-05B out-of-sample evaluation — do not edit
based on model outputs.

Families target *why* models fail, not difficulty:
  bound    — boundary conditions (off-by-one, degenerate inputs)
  cross    — cross-function coordination (shared conventions)
  state    — mutable state with ordering/transition rules
  contract — API shape (exception types, sentinels, signatures)
  fmt      — precise output (escaping, alignment, rounding)

Each family: 2 bug_fix + 2 feature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "eval" / "corpus-s05"
sys.path.insert(0, str(ROOT))
from mril.eval.spec import snapshot_sha256  # noqa: E402

# (task_id, category, api, difficulty, snapshot solution.py, verifier, instruction)
TASKS = []

# ============================================================ bound (boundary)


TASKS.append((
    "bug-bound-window", "bug_fix", "fix", "medium",
    '''def sliding_max(xs, k):
    """Max of each contiguous window of size k. k >= 1."""
    out = []
    for i in range(len(xs) - k):          # BUG: misses final window
        out.append(max(xs[i:i + k]))
    return out
''',
    '''from solution import sliding_max


def test_basic():
    assert sliding_max([1, 3, -1, -3, 5, 3, 6, 7], 3) == [3, 3, 5, 5, 6, 7]


def test_full_window():
    assert sliding_max([4, 2], 2) == [4]
    assert sliding_max([5], 1) == [5]


def test_edges():
    assert sliding_max([], 1) == []
    assert sliding_max([1, 2, 3], 2) == [2, 3]
''',
    "Fix sliding_max(xs, k) in solution.py: it must return the max of every "
    "contiguous length-k window, including the final window and the k==len case. "
    "Currently the last window is dropped. Reply with only the complete file contents.",
))

TASKS.append((
    "bug-bound-range", "bug_fix", "fix", "easy",
    '''def ranges_overlap(a, b):
    """True if inclusive ranges [a0,a1] and [b0,b1] overlap."""
    a0, a1 = a
    b0, b1 = b
    return a0 < b1 and b0 < a1          # BUG: touching endpoints excluded
''',
    '''from solution import ranges_overlap


def test_overlap():
    assert ranges_overlap((1, 5), (3, 8)) is True
    assert ranges_overlap((1, 2), (5, 9)) is False


def test_touching_counts():
    assert ranges_overlap((1, 5), (5, 9)) is True
    assert ranges_overlap((0, 0), (0, 0)) is True


def test_nested():
    assert ranges_overlap((1, 10), (3, 4)) is True
''',
    "Fix ranges_overlap(a, b) in solution.py: ranges are INCLUSIVE — ranges that "
    "touch at an endpoint (e.g. (1,5) and (5,9)) overlap. Currently touching "
    "endpoints return False. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-bound-paginate", "feature", "function", "medium",
    '''def paginate(items, page, per_page):
    """Return the items for 1-based `page` with `per_page` per page.
    Pages past the end return []. per_page >= 1, page >= 1."""
    raise NotImplementedError
''',
    '''from solution import paginate


def test_middle_pages():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_partial_last_page():
    assert paginate(list(range(10)), 4, 3) == [9]
    assert paginate(list(range(7)), 2, 4) == [4, 5, 6]


def test_out_of_range_and_empty():
    assert paginate(list(range(10)), 5, 3) == []
    assert paginate([], 1, 5) == []
    assert paginate([1, 2, 3], 1, 3) == [1, 2, 3]
''',
    "Implement paginate(items, page, per_page) in solution.py: 1-based pages, "
    "per_page items each; a short last page returns what remains; pages past "
    "the end return []. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-bound-clamp", "feature", "function", "easy",
    '''def clamp(v, lo, hi):
    """Clamp v into [lo, hi] inclusive."""
    raise NotImplementedError
''',
    '''from solution import clamp


def test_middle():
    assert clamp(5, 0, 10) == 5


def test_endpoints_inclusive():
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_outside_and_negatives():
    assert clamp(-3, 0, 10) == 0
    assert clamp(99, 0, 10) == 10
    assert clamp(-5, -10, -1) == -5
    assert clamp(-20, -10, -1) == -10
''',
    "Implement clamp(v, lo, hi) in solution.py: returns v bounded into [lo, hi] "
    "inclusive, including negative ranges and exact endpoints. "
    "Reply with only the complete file contents.",
))

# ============================================================ cross (coordination)

TASKS.append((
    "bug-cross-escape", "bug_fix", "fix", "medium",
    '''def encode(s):
    """Escape % and , so encode/decode round-trips on any string."""
    return s.replace(",", "%2C").replace("%", "%25")   # BUG: order wrong


def decode(s):
    return s.replace("%2C", ",").replace("%25", "%")   # BUG: same order bug
''',
    '''from solution import encode, decode


def test_roundtrip_plain():
    assert decode(encode("a,b,c")) == "a,b,c"


def test_roundtrip_percent():
    assert decode(encode("100%")) == "100%"
    assert decode(encode("%2C")) == "%2C"   # literal percent sequence survives


def test_roundtrip_mixed():
    assert decode(encode("a%,b%2C")) == "a%,b%2C"
''',
    "Fix encode/decode in solution.py so decode(encode(s)) == s for ANY string, "
    "including strings that already contain '%' or the literal '%2C'. The two "
    "functions must apply escapes/unescapes in a consistent order. "
    "Reply with only the complete file contents.",
))

TASKS.append((
    "bug-cross-lexer", "bug_fix", "fix", "medium",
    '''def tokenize(expr):
    """Split 'a + -3' into ['a','+','-3']; numbers may be negative."""
    return expr.split()                     # lexer fine


def evaluate(tokens):
    """Evaluate + and - left to right over ints."""
    total = int(tokens[0])
    i = 1
    while i < len(tokens):
        op = tokens[i]
        rhs = int(tokens[i + 1])            # BUG: '-3' ok but parser treats
        if op == '+':                       # a leading '-' on rhs as unary —
            total += rhs                    # actually int() handles it; real bug:
        elif op == '-':                     # rhs never validated, so 'x' crashes
            total -= rhs                    # as ValueError, but contract wants
        i += 2                              # ValueError('bad token') — see tests
    return total


def run(expr):
    return evaluate(tokenize(expr))
''',
    '''import pytest
from solution import run


def test_basic():
    assert run("1 + 2") == 3
    assert run("10 - 4 + 1") == 7


def test_negative_operands():
    assert run("1 + -3") == -2
    assert run("-5 + 5") == 0


def test_bad_token_raises_valueerror():
    with pytest.raises(ValueError, match="bad token"):
        run("1 + x")
''',
    "Fix the tokenizer/evaluator in solution.py: `run('1 + -3')` must equal -2 "
    "and any non-numeric operand must raise ValueError with message 'bad token' "
    "(not a bare conversion error). The lexer and evaluator must agree on what "
    "counts as a number. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-cross-roundtrip", "feature", "function", "hard",
    '''def to_wire(d):
    """Serialize a flat dict {str: int|str|None} to a single-line string.
    Format: 'k=v;k=v' with = and ; percent-escaped in values (and keys)."""
    raise NotImplementedError


def from_wire(s):
    """Inverse of to_wire."""
    raise NotImplementedError
''',
    '''from solution import to_wire, from_wire


def test_roundtrip_basic():
    assert from_wire(to_wire({"a": 1, "b": "x"})) == {"a": 1, "b": "x"}


def test_roundtrip_escapes():
    d = {"k=1": "v;2", "p%": "q"}
    assert from_wire(to_wire(d)) == d


def test_none_and_int():
    d = {"a": None, "n": 0}
    out = from_wire(to_wire(d))
    assert out == d


def test_empty():
    assert from_wire(to_wire({})) == {}
''',
    "Implement to_wire/from_wire in solution.py: serialize a flat dict "
    "{str: int|str|None} to 'k=v;k=v' on one line and back, percent-escaping "
    "'=', ';' and '%' in keys and values so arbitrary content round-trips. "
    "ints must come back as ints, None must survive distinctly from the "
    "string 'None'. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-cross-pipeline", "feature", "function", "medium",
    '''def normalize(rec):
    """Lowercase keys, strip string values. Leave non-str values as-is."""
    raise NotImplementedError


def validate(rec):
    """Return list of error strings; [] when valid. 'name' and 'qty' required,
    qty must be a positive int."""
    raise NotImplementedError


def serialize(rec):
    """'name=x;qty=N' for a VALID normalized record."""
    raise NotImplementedError


def process(rec):
    """normalize -> validate -> serialize. Return serialized string on success,
    'ERR:'-prefixed first error on failure."""
    raise NotImplementedError
''',
    '''from solution import process


def test_happy():
    assert process({"NAME": " widget ", "QTY": 3}) == "name=widget;qty=3"


def test_qty_string_rejected():
    assert process({"name": "x", "qty": "3"}).startswith("ERR:")


def test_missing_fields():
    assert process({"qty": 2}).startswith("ERR:")
    assert process({}).startswith("ERR:")


def test_bad_qty():
    assert process({"name": "x", "qty": 0}).startswith("ERR:")
    assert process({"name": "x", "qty": -1}).startswith("ERR:")
''',
    "Implement normalize/validate/serialize/process in solution.py. normalize "
    "lowercases keys and strips string values; validate returns error strings "
    "(name and qty required, qty a positive int); serialize emits "
    "'name=x;qty=N'; process chains them, returning 'ERR:'+first error on "
    "failure. The stages must agree on normalized key names and value types. "
    "Reply with only the complete file contents.",
))

# ============================================================ state (ordering)

TASKS.append((
    "bug-state-cache", "bug_fix", "class", "medium",
    '''import time


class TTLCache:
    """get() returns None for missing or EXPIRED keys; expired entries must
    not count toward max_size."""

    def __init__(self, max_size=2, ttl=60):
        self.max_size = max_size
        self.ttl = ttl
        self._d = {}

    def set(self, k, v, now=None):
        now = time.time() if now is None else now
        if len(self._d) >= self.max_size:
            oldest = max(self._d, key=lambda k: self._d[k][1])   # BUG: evicts
            del self._d[oldest]                                  # NEWEST entry
        self._d[k] = (v, now)

    def get(self, k, now=None):
        now = time.time() if now is None else now
        if k not in self._d:
            return None
        v, t = self._d[k]
        if now - t > self.ttl:
            return None                                          # BUG: not removed
        return v
''',
    '''from solution import TTLCache


def test_expired_returns_none():
    c = TTLCache(max_size=2, ttl=10)
    c.set("a", 1, now=0)
    assert c.get("a", now=5) == 1
    assert c.get("a", now=11) is None


def test_expired_frees_slot():
    c = TTLCache(max_size=2, ttl=10)
    c.set("a", 1, now=0)
    c.set("b", 2, now=0)
    # a and b expire; inserting c must NOT evict anything still fresh
    c.set("c", 3, now=20)
    assert c.get("c", now=21) == 3


def test_evicts_oldest_fresh():
    c = TTLCache(max_size=2, ttl=100)
    c.set("a", 1, now=0)
    c.set("b", 2, now=1)
    c.set("c", 3, now=2)
    assert c.get("a", now=3) is None
    assert c.get("b", now=3) == 2
    assert c.get("c", now=3) == 3
''',
    "Fix TTLCache in solution.py: expired entries must return None AND free "
    "their slot — an expired entry must never block or be counted when "
    "evicting. set() must evict the oldest *unexpired* entry only when the "
    "cache is full of fresh entries. Reply with only the complete file contents.",
))

TASKS.append((
    "bug-state-undo", "bug_fix", "class", "medium",
    '''class UndoStack:
    """Actions are grouped: end_group() seals the current group; undo()
    reverses the LAST sealed group (or the open group)."""

    def __init__(self):
        self._groups = []
        self._open = []

    def do(self, action):
        self._open.append(action)

    def end_group(self):
        self._groups.append(self._open)
        self._open = []

    def undo(self):
        # BUG: prefers sealed groups over the still-open one and returns
        # members in insertion order instead of reverse-insertion order.
        if self._groups:
            return self._groups.pop()
        g, self._open = self._open, []
        return g
''',
    '''from solution import UndoStack


def test_simple():
    u = UndoStack()
    u.do("a"); u.do("b"); u.end_group()
    assert u.undo() == ["b", "a"]


def test_open_group_undone_first():
    u = UndoStack()
    u.do("a"); u.end_group()
    u.do("c")
    assert u.undo() == ["c"]
    assert u.undo() == ["a"]


def test_group_order():
    u = UndoStack()
    u.do("a"); u.end_group()
    u.do("b"); u.do("c"); u.end_group()
    assert u.undo() == ["c", "b"]
    assert u.undo() == ["a"]
    assert u.undo() == []
''',
    "Fix UndoStack in solution.py: actions between end_group() calls form one "
    "group; undo() reverses the most recent group — the still-open group "
    "first, then sealed groups newest-first — returning members in reverse "
    "insertion order. Empty stack returns []. Reply with only the complete "
    "file contents.",
))

TASKS.append((
    "impl-state-session", "feature", "class", "medium",
    '''class SessionCounter:
    """Counts events per session. add(n) increments the CURRENT session;
    rollover() starts a new session; total() sums only completed sessions;
    current() reports the open session count."""

    def __init__(self):
        raise NotImplementedError
''',
    '''from solution import SessionCounter


def test_flow():
    s = SessionCounter()
    s.add(2); s.add(3)
    assert s.current() == 5
    assert s.total() == 0          # open session not counted yet
    s.rollover()
    assert s.current() == 0
    assert s.total() == 5


def test_multiple():
    s = SessionCounter()
    s.add(1); s.rollover()
    s.add(2); s.add(2); s.rollover()
    s.add(7)
    assert s.total() == 5
    assert s.current() == 7
''',
    "Implement SessionCounter in solution.py: add(n) counts into the open "
    "session; rollover() seals it and starts a fresh one; total() sums ONLY "
    "sealed sessions; current() reports the open one. Reply with only the "
    "complete file contents.",
))

TASKS.append((
    "impl-state-circuit", "feature", "class", "hard",
    '''class CircuitBreaker:
    """closed -> open after `threshold` CONSECUTIVE failures.
    open: calls rejected (call() returns 'OPEN').
    after `reset_after` ticks the next call is a probe -> half-open:
    success closes the circuit; failure reopens it (failure count resets).
    call(ok, t) records success/failure at time t and returns
    'ok' | 'fail' | 'open'."""

    def __init__(self, threshold=3, reset_after=30):
        raise NotImplementedError
''',
    '''from solution import CircuitBreaker


def test_opens_after_threshold():
    c = CircuitBreaker(threshold=2, reset_after=10)
    assert c.call(False, 0) == "fail"
    assert c.call(False, 1) == "fail"
    assert c.call(True, 2) == "open"          # rejected, not counted


def test_probe_and_recover():
    c = CircuitBreaker(threshold=1, reset_after=10)
    c.call(False, 0)                          # opens
    assert c.call(True, 5) == "open"          # still cooling
    assert c.call(True, 11) == "ok"           # probe succeeds -> closed
    assert c.call(True, 12) == "ok"


def test_probe_failure_reopens():
    c = CircuitBreaker(threshold=1, reset_after=10)
    c.call(False, 0)
    assert c.call(False, 11) == "fail"        # probe fails -> open again
    assert c.call(True, 15) == "open"
    assert c.call(True, 22) == "ok"


def test_success_resets_streak():
    c = CircuitBreaker(threshold=2, reset_after=10)
    c.call(False, 0); c.call(True, 1)
    c.call(False, 2); c.call(False, 3)
    assert c.call(True, 4) == "open"
''',
    "Implement CircuitBreaker in solution.py: `threshold` consecutive failures "
    "open the circuit; while open, call() returns 'open' without counting; "
    "after reset_after ticks a call becomes a probe — success closes the "
    "circuit (streak reset), failure reopens it. A success in closed state "
    "resets the consecutive-failure streak. Reply with only the complete "
    "file contents.",
))

# ============================================================ contract

TASKS.append((
    "bug-contract-sentinel", "bug_fix", "fix", "easy",
    '''MISSING = object()


def lookup(d, path, default=MISSING):
    """lookup({'a': {'b': 1}}, 'a.b') -> 1. Missing path -> default if given,
    else KeyError."""
    cur = d
    for part in path.split("."):
        if part not in cur:
            return default            # BUG: returns the sentinel object and
        cur = cur[part]               # never raises even without default
    return cur
''',
    '''import pytest
from solution import lookup


def test_hit():
    assert lookup({"a": {"b": 1}}, "a.b") == 1
    assert lookup({"a": 5}, "a") == 5


def test_default():
    assert lookup({}, "x", default=0) == 0
    assert lookup({"a": {}}, "a.b", default=None) is None


def test_missing_raises():
    with pytest.raises(KeyError):
        lookup({}, "nope")
    with pytest.raises(KeyError):
        lookup({"a": {}}, "a.b")
''',
    "Fix lookup(d, path, default) in solution.py: dotted-path dict access — "
    "return default ONLY when the caller provided one (the default sentinel "
    "must never leak as a return value); otherwise raise KeyError. "
    "Reply with only the complete file contents.",
))

TASKS.append((
    "bug-contract-exc", "bug_fix", "fix", "easy",
    '''class OrderError(Exception):
    pass


def place_order(qty, stock):
    """qty must be positive int and <= stock, else OrderError."""
    if qty <= 0:
        raise ValueError("qty must be positive")      # BUG: wrong exception type
    if qty > stock:
        raise RuntimeError("insufficient stock")      # BUG: wrong exception type
    return stock - qty
''',
    '''import pytest
from solution import OrderError, place_order


def test_ok():
    assert place_order(2, 5) == 3


def test_bad_qty_raises_ordererror():
    with pytest.raises(OrderError):
        place_order(0, 5)
    with pytest.raises(OrderError):
        place_order(-1, 5)


def test_stock_raises_ordererror():
    with pytest.raises(OrderError):
        place_order(10, 5)


def test_non_int_rejected():
    with pytest.raises(OrderError):
        place_order(2.5, 5)
''',
    "Fix place_order in solution.py: every contract violation — non-positive, "
    "non-int, or over-stock quantity — must raise OrderError (the declared "
    "exception), not ValueError/RuntimeError. Valid orders return remaining "
    "stock. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-contract-result", "feature", "function", "medium",
    '''def ok(v):
    """Wrap a success value."""
    raise NotImplementedError


def err(msg):
    """Wrap an error message."""
    raise NotImplementedError


def is_ok(r):
    raise NotImplementedError


def unwrap(r):
    """Return the success value; if r is an error, raise RuntimeError(msg)."""
    raise NotImplementedError


def map_result(r, fn):
    """ok -> ok(fn(v)); error passes through unchanged."""
    raise NotImplementedError
''',
    '''import pytest
from solution import err, is_ok, map_result, ok, unwrap


def test_roundtrip():
    assert is_ok(ok(3)) is True
    assert is_ok(err("bad")) is False
    assert unwrap(ok(3)) == 3


def test_unwrap_error_raises():
    with pytest.raises(RuntimeError, match="bad"):
        unwrap(err("bad"))


def test_map():
    assert unwrap(map_result(ok(2), lambda x: x * 10)) == 20
    r = map_result(err("e"), lambda x: x * 10)
    assert is_ok(r) is False
    with pytest.raises(RuntimeError):
        unwrap(r)


def test_falsy_values_survive():
    assert unwrap(ok(0)) == 0
    assert is_ok(ok(None)) is True
''',
    "Implement ok/err/is_ok/unwrap/map_result in solution.py — a Result-style "
    "API: ok(v) and err(msg) wrap outcomes, is_ok discriminates (falsy payloads "
    "like 0 or None still count as ok), unwrap returns the value or raises "
    "RuntimeError(msg), map_result transforms successes and passes errors "
    "through. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-contract-iter", "feature", "function", "hard",
    '''def windowed(it, n):
    """Yield successive n-tuples over `it`, sliding by one, lazily.
    windowed(range(5), 3) -> (0,1,2),(1,2,3),(2,3,4).
    Must work on any iterable (incl. generators), yield tuples not lists,
    and not materialize the whole input."""
    raise NotImplementedError
''',
    '''from solution import windowed


def test_basic():
    assert list(windowed(range(5), 3)) == [(0, 1, 2), (1, 2, 3), (2, 3, 4)]


def test_returns_tuples():
    first = next(iter(windowed([1, 2, 3], 2)))
    assert isinstance(first, tuple)


def test_short_input():
    assert list(windowed([1], 2)) == []
    assert list(windowed([], 1)) == []
    assert list(windowed([1, 2], 2)) == [(1, 2)]


def test_lazy_single_pass():
    seen = []

    def gen():
        for i in range(10):
            seen.append(i)
            yield i

    it = windowed(gen(), 3)
    next(it)
    assert len(seen) <= 4         # must not consume all 10 up front
    assert len(list(it)) == 7
''',
    "Implement windowed(it, n) in solution.py: lazily yield successive "
    "n-tuples sliding by one over ANY iterable including generators — tuples "
    "not lists, no full materialization, fewer than n elements yields "
    "nothing. Reply with only the complete file contents.",
))

# ============================================================ fmt (precise output)

TASKS.append((
    "bug-fmt-currency", "bug_fix", "fix", "easy",
    '''def money(cents):
    """Cents -> '$1,234.56'; negatives '-$1.23'; rounds half-up on odd cents
    already being exact (input is int cents)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100}"   # BUG: no padding/commas
''',
    '''from solution import money


def test_basic():
    assert money(123456) == "$1,234.56"
    assert money(5) == "$0.05"
    assert money(50) == "$0.50"


def test_negative():
    assert money(-123) == "-$1.23"
    assert money(-1000000) == "-$10,000.00"


def test_zero_and_thousands():
    assert money(0) == "$0.00"
    assert money(100000) == "$1,000.00"
''',
    "Fix money(cents) in solution.py: format as '$1,234.56' with two-digit "
    "cents (zero-padded), thousands separators, and '-' before the '$' for "
    "negatives. Reply with only the complete file contents.",
))

TASKS.append((
    "bug-fmt-table", "bug_fix", "fix", "medium",
    '''def render_table(rows, widths):
    """rows: list of str lists; widths: column widths. Cells left-aligned,
    space-padded to width, columns joined with ' | '. Missing cells count
    as empty."""
    lines = []
    for row in rows:
        cells = [row[i] if i < len(row) else "" for i in range(len(widths))]
        # BUG: truncates over-wide content instead of letting it overflow
        lines.append(" | ".join(c[:w].ljust(w) for c, w in zip(cells, widths)))
    return "\\n".join(lines)
''',
    '''from solution import render_table


def test_basic():
    out = render_table([["a", "bb"], ["ccc", "d"]], [3, 2])
    assert out == "a   | bb\\nccc | d "


def test_missing_cells():
    out = render_table([["x"], ["y", "z", "extra"]], [2, 2])
    assert out == "x  |   \\ny  | z "   # extra cell beyond widths dropped


def test_wide_cells_not_truncated():
    out = render_table([["longer", "b"]], [2, 1])
    assert out == "longer | b"
''',
    "Fix render_table(rows, widths) in solution.py: left-align each cell "
    "space-padded to its column width, join with ' | ', treat missing cells "
    "as empty and drop cells beyond the width list; do NOT truncate "
    "over-wide content. Reply with only the complete file contents.",
))

TASKS.append((
    "impl-fmt-sql", "feature", "function", "medium",
    '''def quote_ident(name):
    """SQL identifier -> "name" (double-quoted, inner quotes doubled)."""
    raise NotImplementedError


def quote_literal(val):
    """SQL string literal -> 'val' (single-quoted, inner quotes doubled).
    ints/floats pass through unquoted; None -> NULL."""
    raise NotImplementedError


def insert(table, row):
    """INSERT INTO "t" ("c1","c2") VALUES ('v',1); row is {col: val}."""
    raise NotImplementedError
''',
    '''from solution import insert, quote_ident, quote_literal


def test_ident():
    assert quote_ident("users") == '"users"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_literal():
    assert quote_literal("o'brien") == "'o''brien'"
    assert quote_literal(42) == "42"
    assert quote_literal(None) == "NULL"


def test_insert():
    assert insert("t", {"a": "x", "n": 1}) == "INSERT INTO \\"t\\" (\\"a\\",\\"n\\") VALUES ('x',1)"


def test_insert_quotes():
    assert insert("t", {"a": "it's"}) == "INSERT INTO \\"t\\" (\\"a\\") VALUES ('it''s')"
''',
    "Implement quote_ident/quote_literal/insert in solution.py: identifiers "
    "double-quoted with internal quotes doubled; string literals single-quoted "
    "with quotes doubled; numbers unquoted; None as NULL; insert emits "
    "INSERT INTO \"t\" (\"c1\",\"c2\") VALUES (...) in row order. "
    "Reply with only the complete file contents.",
))

TASKS.append((
    "impl-fmt-diff", "feature", "function", "medium",
    '''def diff_lines(old, new):
    """Unified-style line diff, simplest form:
    lines only in old -> '-line' (in order)
    lines only in new -> '+line' (in order, after all removals)
    lines identical at same index are skipped.
    Compare by full-line equality; a changed line = '-' then '+'."""
    raise NotImplementedError
''',
    '''from solution import diff_lines


def test_change():
    assert diff_lines(["a", "b"], ["a", "c"]) == "-b\\n+c"


def test_add_remove():
    assert diff_lines(["a"], ["a", "b"]) == "+b"
    assert diff_lines(["a", "b"], ["a"]) == "-b"


def test_no_change_and_empty():
    assert diff_lines(["x"], ["x"]) == ""
    assert diff_lines([], ["n"]) == "+n"
    assert diff_lines(["o"], []) == "-o"


def test_multi():
    assert diff_lines(["a", "b", "c"], ["a", "x", "y"]) == "-b\\n-c\\n+x\\n+y"
''',
    "Implement diff_lines(old, new) in solution.py: compare lines pairwise by "
    "index — emit '-line' for every line removed/changed (in order), then "
    "'+line' for every added/changed line (in order); identical lines emit "
    "nothing; output is newline-joined, empty when inputs match. "
    "Reply with only the complete file contents.",
))


def main():
    CORPUS.mkdir(parents=True, exist_ok=True)
    assert len(TASKS) == 20, len(TASKS)
    for tid, category, api, difficulty, solution, verifier, instruction in TASKS:
        fam = tid.split("-")[1]
        d = CORPUS / tid
        (d / "snapshot").mkdir(parents=True, exist_ok=True)
        (d / "verifiers").mkdir(parents=True, exist_ok=True)
        (d / "snapshot" / "solution.py").write_text(solution, encoding="utf-8")
        (d / "verifiers" / f"test_{fam[0]}.py").write_text(verifier, encoding="utf-8")
        snap = d / "snapshot"
        spec = {
            "id": tid,
            "schema_version": 1,
            "repository": {
                "snapshot": f"{tid}/snapshot",
                "sha256": snapshot_sha256(snap),
            },
            "task": {
                "instruction": instruction,
                "language": "python",
                "category": category,
                "scope": "single_module",
                "risk": "medium" if difficulty != "hard" else "high",
                "target_file": "solution.py",
            },
            "verification": {
                "files": [f"{tid}/verifiers/test_{fam[0]}.py"],
                "command": f"{{python}} -m pytest {{verify}}test_{fam[0]}.py -q",
                "timeout_seconds": 60,
            },
            "limits": {
                "max_attempts": 3,
                "max_model_calls": 8,
                "max_wall_seconds": 600,
                "budget_usd": 0.5,
            },
            "metadata": {
                "difficulty": difficulty,
                "family": fam,
                "cell_api": api,
            },
        }
        (d / "task.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(tid, spec["repository"]["sha256"][:12])


if __name__ == "__main__":
    main()
