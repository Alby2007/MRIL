loaded 312 task-executions, 39 distinct tasks

## 1-3. coverage + outcomes per (prev_model, category, attempt_count, action)
prev        category          @att action    next          tasks n   pass CI95           cost     lat
strong-coderassertion_failure 1    escalate  weak-coder    9     12  0/12 [0.00,0.24]    $0.0002  1304ms
strong-coderassertion_failure 1    retry     strong-coder  9     13  2/13 [0.04,0.42]    $0.0081  7832ms
strong-coderassertion_failure 1    stop      -             6     9   0/9 [0.00,0.30]     -        -
strong-coderassertion_failure 2    escalate  weak-coder    8     10  0/10 [-0.00,0.28]   $0.0002  1479ms
strong-coderassertion_failure 2    retry     strong-coder  5     6   2/6 [0.10,0.70]     $0.0063  6032ms
strong-coderassertion_failure 2    stop      -             5     5   0/5 [-0.00,0.43]    -        -
strong-coderassertion_failure 3    stop      -             9     15  0/15 [-0.00,0.20]   -        -
strong-codercontract_error    3    stop      -             1     1   0/1 [0.00,0.79]     -        -
strong-coderruntime_error     1    escalate  weak-coder    3     5   0/5 [-0.00,0.43]    $0.0002  1431ms
strong-coderruntime_error     1    retry     strong-coder  2     3   0/3 [0.00,0.56]     $0.0074  6153ms
strong-coderruntime_error     1    stop      -             2     2   0/2 [0.00,0.66]     -        -
strong-coderruntime_error     2    escalate  weak-coder    2     2   0/2 [0.00,0.66]     $0.0002  1097ms
strong-coderruntime_error     2    retry     strong-coder  2     2   1/2 [0.09,0.91]     $0.0077  6873ms
strong-coderruntime_error     2    stop      -             5     5   0/5 [-0.00,0.43]    -        -
strong-coderruntime_error     3    stop      -             3     3   0/3 [0.00,0.56]     -        -
strong-codersyntax_error      2    retry     strong-coder  1     2   0/2 [0.00,0.66]     $0.0075  6417ms
strong-codersyntax_error      2    stop      -             2     2   0/2 [0.00,0.66]     -        -
strong-codersyntax_error      3    stop      -             1     1   0/1 [0.00,0.79]     -        -
weak-coder  assertion_failure 1    escalate  strong-coder  12    23  10/23 [0.26,0.63]   $0.0073  7005ms
weak-coder  assertion_failure 1    retry     weak-coder    10    16  0/16 [0.00,0.19]    $0.0002  1019ms
weak-coder  assertion_failure 1    stop      -             8     12  0/12 [0.00,0.24]    -        -
weak-coder  assertion_failure 2    escalate  strong-coder  10    12  2/12 [0.05,0.45]    $0.0080  8250ms
weak-coder  assertion_failure 2    retry     weak-coder    8     8   0/8 [0.00,0.32]     $0.0002  947ms
weak-coder  assertion_failure 2    stop      -             9     9   0/9 [0.00,0.30]     -        -
weak-coder  assertion_failure 3    stop      -             12    17  0/17 [0.00,0.18]    -        -
weak-coder  contract_error    1    retry     weak-coder    1     1   0/1 [0.00,0.79]     $0.0002  747ms
weak-coder  contract_error    2    stop      -             2     2   0/2 [0.00,0.66]     -        -
weak-coder  runtime_error     1    escalate  strong-coder  7     10  3/10 [0.11,0.60]    $0.0066  5683ms
weak-coder  runtime_error     1    retry     weak-coder    6     9   1/9 [0.02,0.44]     $0.0002  1281ms
weak-coder  runtime_error     1    stop      -             6     8   0/8 [0.00,0.32]     -        -
weak-coder  runtime_error     2    escalate  strong-coder  4     4   1/4 [0.05,0.70]     $0.0107  10194ms
weak-coder  runtime_error     2    retry     weak-coder    2     3   0/3 [0.00,0.56]     $0.0001  939ms
weak-coder  runtime_error     2    stop      -             4     4   0/4 [0.00,0.49]     -        -
weak-coder  runtime_error     3    stop      -             5     6   0/6 [0.00,0.39]     -        -

## 2. propensity integrity
  |feas|=3: draws={'switch:strong-coder': 49, 'stop:-': 58, 'retry:weak-coder': 37, 'retry:strong-coder': 26, 'switch:weak-coder': 29} (chi2 vs uniform = 64.08, crit@.05 ≈ 5.99)
  forced (|feas|=1, terminal): 43 decisions

## 4. pooled yields, weak-fail @1 by action
  escalate   13/33 = 0.39 [0.25,0.56] (18 tasks)
  retry      1/26 = 0.04 [0.01,0.19] (15 tasks)

## 4b. pooled yields, strong-fail @1 by action
  escalate:weak-coder    0/17 = 0.00 [0.00,0.18] (12 tasks)
  retry:strong-coder     2/16 = 0.12 [0.03,0.36] (11 tasks)

## 5. category informativeness (weak-fail @1 -> escalate yield)
  runtime_error      3/10 [0.11,0.60]
  assertion_failure  10/23 [0.26,0.63]

## invalid evidence check
  (None, 211)
  ('assertion_failure', 167)
  ('contract_error', 4)
  ('runtime_error', 66)
  ('syntax_error', 5)
