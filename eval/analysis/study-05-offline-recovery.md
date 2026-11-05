attempt chains loaded: 738 task-executions (39 distinct tasks, 156 task×arm cells)

## A. failure-to-recovery transition table (OBSERVED cells only)
prev model  fail type     action    next model   distinct tasks transitions next-att succ         mean next cost mean next lat
strong-codertest_failure  retry     strong-coder 12             101         8/101 [0.04,0.15]     $0.0097        10281ms
strong-codertest_failure  stop      None         18             165         0/165 [0.00,0.02]     —              —
weak-coder  test_failure  escalate  strong-coder 22             125         53/125 [0.34,0.51]    $0.0075        6984ms

UNOBSERVED (unsupported, not p=0): weak→retry-weak, weak→stop, any action on a failure category other than test_failure, any 3rd attempt.

## B. recovery decisions by attempts used (OBSERVED)
  attempt_count=1/3: {'escalate': 125, 'retry': 101}
  attempt_count=2/3: {'stop': 165}
  -> policy deterministically maps (model, attempt_count) to action; remaining-attempt sensitivity is unobservable beyond this boundary.

## C. strong retry-after-strong-fail vs strong rescue-after-weak-fail
  rescue (weak failed -> strong): 53/125 = 0.42 CI95[0.34,0.51] over 22 distinct tasks; mean next-att cost $0.0075, lat 6984ms
  retry  (strong failed -> strong): 8/101 = 0.08 CI95[0.04,0.15] over 12 distinct tasks; mean next-att cost $0.0097, lat 10281ms
  OBSERVED rates; comparison is NOT causal (different task mixes/histories).

## D. task-level recoverability (OBSERVED; 3 seeds is not proof of permanent ceiling)
  task                      weak pass   strong pass  rescue after weak fail
  bug-add                   20/20       10/10        —
  bug-binary-search         13/13       17/17        —
  bug-dt-between            2/6         8/10         2/4
  bug-dt-months             0/6         4/18         4/6
  bug-fizzbuzz              13/13       17/17        —
  bug-flatten               20/20       10/10        —
  bug-late-binding          12/13       18/18        1/1
  bug-multi-counter         3/6         9/9          3/3
  bug-multi-shared          6/6         6/6          —
  bug-mutable-default       13/13       17/17        —
  bug-regex-loglines        6/6         6/6          —
  bug-regex-pairs           6/6         6/6          —
  bug-serde-fields          6/6         6/6          —
  bug-serde-nested          0/6         2/18         0/6
  bug-tmpl-escape           0/6         10/12        4/6
  bug-tmpl-repeat           6/6         6/6          —
  bug-validate-age          6/6         6/6          —
  bug-validate-order        0/6         12/12        6/6
  class-bank                13/13       17/17        —
  impl-csv-line             0/10        0/50         0/10  <- ceiling candidate (strong never verified)
  impl-dt-business          0/6         4/18         1/6
  impl-dt-weekday           6/6         6/6          —
  impl-ini-parse            0/10        27/30        7/10
  impl-lru-cache            13/13       17/17        —
  impl-merge-intervals      12/13       17/18        0/1
  impl-multi-stack          0/6         8/12         2/6
  impl-multi-undo           0/6         2/18         0/6
  impl-palindrome           20/20       10/10        —
  impl-rate-limiter         0/10        5/50         5/10
  impl-regex-logparse       0/3         1/21         1/3
  impl-regex-slug           0/6         0/18         0/6  <- ceiling candidate (strong never verified)
  impl-roman                13/13       17/17        —
  impl-serde-basic          6/6         6/6          —
  impl-serde-versioned      0/6         2/18         2/6
  impl-tmpl-basic           2/6         6/10         0/4
  impl-tmpl-strict          0/3         0/21         0/3  <- ceiling candidate (strong never verified)
  impl-topk-words           0/10        29/31        9/10
  impl-validate-form        0/6         12/12        6/6
  impl-validate-request     0/6         0/18         0/6  <- ceiling candidate (strong never verified)

## E. evidence classification
  OBSERVED: weak-fail→escalate→strong transitions; strong-fail→retry→strong;
            strong-fail@2→stop; next-attempt cost/latency/outcome for each.
  ESTIMATED (only via model): per-task weak/strong pass rates above.
  NOT IDENTIFIABLE from this ledger:
    - weak retry after weak failure (0 propensity across all ledgers)
    - stop after first weak failure (never observed)
    - any recovery action on failure categories other than test_failure
      (no contract/syntax/api-error/timeout failures were ever recorded)
    - any 3rd attempt (policy stops at attempt_count=2; max_attempts=3 unused)
    - retry vs escalate *choice* under identical context (policy is deterministic:
      weak-fail@1→escalate, strong-fail@1→retry — no within-cell action variation)

  SAFEGUARD: no 'recovery policy X would save Y%' claim is supportable
  from these data — the alternative arms lack propensity coverage.
