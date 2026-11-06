def tokenize(expr):
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
