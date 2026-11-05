"""Generate task.json specs for the Study 04 corpus (24 tasks, 6 families x 4 cells).

Cell design: {bug_fix, feature} x {no rule markers, multiple rule markers}.
No-marker instructions deliberately avoid all marker vocabulary; marker
cells deliberately carry >= 2 groups. api_kind varies across families.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mril.eval.spec import snapshot_sha256  # noqa: E402

ROOT = Path("eval/corpus-s04")

# id -> (instruction, category, risk, difficulty, target, [verifier files], test file)
TASKS = {
    # ---- tmpl ---------------------------------------------------------------
    "bug-tmpl-repeat": dict(
        i=("Fix render(template, values) in solution.py: it substitutes every "
           "{key} placeholder with the matching value from values. Currently "
           "only the first occurrence of each placeholder gets replaced."),
        cat="bug_fix", risk="medium", diff="medium", api="fix", t="solution.py",
        vf="test_t.py"),
    "bug-tmpl-escape": dict(
        i=("Fix render(template, values) in solution.py: {{ and }} escape to a "
           "literal single brace, {name} substitutes from values, and a missing "
           "key keeps its placeholder written out instead of being invalid."),
        cat="bug_fix", risk="high", diff="hard", api="fix", t="solution.py",
        vf="test_t.py"),
    "impl-tmpl-basic": dict(
        i=("Implement render(template, values) in solution.py: take a string "
           "with {name} placeholders and a dict of values, and give back the "
           "string with every placeholder swapped for its value. A placeholder "
           "whose key is not in the dict stays written out with braces."),
        cat="feature", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_t.py"),
    "impl-tmpl-strict": dict(
        i=("Implement render(template, values) in solution.py: {{ and }} escape "
           "to literal braces; {name} substitutes from values coerced with "
           "str(); {name:>5} pads the coerced value right in a field of width "
           "5; an absent key renders as empty text."),
        cat="feature", risk="high", diff="hard", api="function",
        t="solution.py", vf="test_t.py"),
    # ---- dt -----------------------------------------------------------------
    "bug-dt-between": dict(
        i=("Fix days_between(a, b) in solution.py: give back how many days "
           "separate the two dates, always as a non-negative count. Right now "
           "a later first argument gives a negative result."),
        cat="bug_fix", risk="medium", diff="medium", api="fix", t="solution.py",
        vf="test_d.py"),
    "bug-dt-months": dict(
        i=("Fix add_months(d, n) in solution.py: adding n months must roll "
           "over year boundaries and clamp the day to the last valid int day "
           "of the target month — Jan 31 + 1 lands on Feb 28 or 29. Currently "
           "it produces an invalid date or the wrong month."),
        cat="bug_fix", risk="high", diff="hard", api="fix", t="solution.py",
        vf="test_d.py"),
    "impl-dt-weekday": dict(
        i=("Implement weekday_name(d) in solution.py: given a datetime.date "
           "value, give back the English weekday name such as 'Monday'."),
        cat="feature", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_d.py"),
    "impl-dt-business": dict(
        i=("Implement business_days(start, end, holidays) in solution.py: "
           "count Mon-Fri days between two ISO date strings, inclusive of "
           "start but excluding end; holiday strings are skipped; an invalid "
           "date string raises ValueError; when start is after end the count "
           "is a negative int of the reversed span."),
        cat="feature", risk="high", diff="hard", api="function",
        t="solution.py", vf="test_d.py"),
    # ---- regex --------------------------------------------------------------
    "bug-regex-pairs": dict(
        i=("The pairs(text) function in solution.py is broken: repair it so "
           "it collects every key=value occurrence in the text and gives back "
           "a list of (key, value) tuples. Right now only the first occurrence "
           "comes back."),
        cat="bug_fix", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_r.py"),
    "bug-regex-loglines": dict(
        i=("Fix count_errors(text) in solution.py: count how many lines begin "
           "with 'ERROR'. Lines may be empty or hold any other text; "
           "whitespace-only lines are skipped without error; the tally covers "
           "every line, not just the start of the whole string."),
        cat="bug_fix", risk="high", diff="hard", api="fix", t="solution.py",
        vf="test_r.py"),
    "impl-regex-slug": dict(
        i=("Implement slugify(text) in solution.py: lowercase the text, turn "
           "each run of spaces and underscores into one hyphen, keep only "
           "letters, digits and hyphens, and drop hyphens at either end."),
        cat="feature", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_r.py"),
    "impl-regex-logparse": dict(
        i=("Implement parse_log_line(line) in solution.py: parse '[LEVEL] "
           "message (code NNN)' into a dict with keys level, message, code "
           "where code is an int; lines that don't match the shape, have an "
           "invalid level (only DEBUG INFO WARN ERROR allowed), or are empty "
           "give back None rather than raising."),
        cat="feature", risk="high", diff="hard", api="function",
        t="solution.py", vf="test_r.py"),
    # ---- multi --------------------------------------------------------------
    "bug-multi-shared": dict(
        i=("The helpers in solution.py share a module-level list: repair them "
           "so add(item) appends to it and total() gives back the running sum "
           "of everything added. Right now total() always gives back 0."),
        cat="bug_fix", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_m.py"),
    "bug-multi-counter": dict(
        i=("Fix WordCounter in solution.py: add(word) tallies words and top() "
           "gives back the most frequent one; an empty counter gives back "
           "None. Right now top() returns the first word ever added."),
        cat="bug_fix", risk="high", diff="hard", api="class", t="solution.py",
        vf="test_m.py"),
    "impl-multi-stack": dict(
        i=("Implement a small stack calculator in solution.py: push(v) and "
           "pop() work on a shared stack, and apply(op) performs the given op "
           "where op is 'add', 'sub', 'mul' or 'neg' — the first three "
           "combine the top two values and 'neg' flips the sign of the top "
           "one. pop or apply with too few values raises IndexError."),
        cat="feature", risk="medium", diff="medium", api="function",
        t="solution.py", vf="test_m.py"),
    "impl-multi-undo": dict(
        i=("Implement TextBuffer in solution.py: it tracks writes and "
           "deletes — write(text) appends, delete(n) drops the last n chars, "
           "undo() reverts the most recent op, contents() gives back the "
           "text, an empty buffer renders as ''. undo() with nothing left to "
           "revert changes nothing."),
        cat="feature", risk="high", diff="hard", api="class", t="solution.py",
        vf="test_m.py"),
    # ---- serde --------------------------------------------------------------
    "bug-serde-fields": dict(
        i=("The record helpers in solution.py lose a field on the way to a "
           "dict and back: repair them so person_to_dict then dict_to_person "
           "gives back an equivalent record."),
        cat="bug_fix", risk="medium", diff="medium", api="class",
        t="solution.py", vf="test_s.py"),
    "bug-serde-nested": dict(
        i=("The serializer helpers in solution.py are broken: repair them so "
           "nested Item records become dicts, fields holding None or missing "
           "from the output stay out, and a full round trip reproduces the "
           "record."),
        cat="bug_fix", risk="high", diff="hard", api="class", t="solution.py",
        vf="test_s.py"),
    "impl-serde-basic": dict(
        i=("Implement product_to_dict(p) and dict_to_product(d) in "
           "solution.py for the Product class provided: give back a dict "
           "with the same fields going each way so a record survives the "
           "trip there and back."),
        cat="feature", risk="medium", diff="medium", api="class",
        t="solution.py", vf="test_s.py"),
    "impl-serde-versioned": dict(
        i=("Implement serialize(e) and deserialize(d) in solution.py: "
           "serialize gives back a dict tagged {'v': 2}; fields holding None "
           "or missing stay out; qty is coerced to int; deserialize rebuilds "
           "the Entry and raises ValueError on any unknown key."),
        cat="feature", risk="high", diff="hard", api="class", t="solution.py",
        vf="test_s.py"),
    # ---- validate -----------------------------------------------------------
    "bug-validate-age": dict(
        i=("Fix check_user(d) in solution.py: name must be a non-blank str "
           "and age must be at least 0, giving back True on success and "
           "raising ValueError otherwise. Right now negative ages are "
           "accepted."),
        cat="bug_fix", risk="medium", diff="medium", api="fix", t="solution.py",
        vf="test_v.py"),
    "bug-validate-order": dict(
        i=("Fix validate_order(quantity, price, status) in solution.py: "
           "quantity must be a positive int, price at least 0, and status "
           "one of the allowed labels; anything else is invalid and raises "
           "ValueError."),
        cat="bug_fix", risk="high", diff="hard", api="fix", t="solution.py",
        vf="test_v.py"),
    "impl-validate-form": dict(
        i=("Implement a FormValidator class in solution.py: constructed with "
           "a dict of fields; require(name) adds a demanded field; is_valid() "
           "gives back True when every demanded field is present and "
           "non-blank; the errors property gives back the demanded names "
           "that failed."),
        cat="feature", risk="medium", diff="medium", api="class",
        t="solution.py", vf="test_v.py"),
    "impl-validate-request": dict(
        i=("Implement a RequestValidator class in solution.py: constructed "
           "with a spec dict mapping field -> ('required'|'optional', type, "
           "lo, hi); validate(payload) accumulates every problem — a missing "
           "required field, a wrong type like an int given a str, an "
           "out-of-range value, or an unknown key which is invalid — into "
           ".errors and gives back False."),
        cat="feature", risk="high", diff="hard", api="class", t="solution.py",
        vf="test_v.py"),
}

FAMILY = {
    "tmpl": "templating", "dt": "datetime", "regex": "regex_parsing",
    "multi": "multi_function", "serde": "serialization", "validate": "api_validation",
}


def family_of(task_id: str) -> str:
    for k, v in FAMILY.items():
        if f"-{k}-" in task_id:
            return v
    return "unknown"


def main() -> None:
    for tid, t in TASKS.items():
        snap = ROOT / tid / "snapshot"
        spec = {
            "id": tid,
            "schema_version": 1,
            "repository": {
                "snapshot": f"{tid}/snapshot",
                "sha256": snapshot_sha256(snap),
            },
            "task": {
                "instruction": t["i"] + " Reply with only the complete file contents.",
                "language": "python",
                "category": t["cat"],
                "scope": "single_module",
                "risk": t["risk"],
                "target_file": t["t"],
            },
            "verification": {
                "files": [f"{tid}/verifiers/{t['vf']}"],
                "command": "{python} -m pytest {verify}" + t["vf"] + " -q",
                "timeout_seconds": 60,
            },
            "limits": {
                "max_attempts": 3,
                "max_model_calls": 8,
                "max_wall_seconds": 600,
                "budget_usd": 0.5,
            },
            "metadata": {
                "difficulty": t["diff"],
                "family": family_of(tid),
                "cell_api": t["api"],
            },
        }
        out = ROOT / tid / "task.json"
        out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(tid, spec["repository"]["sha256"][:12])


if __name__ == "__main__":
    main()
