from solution import to_roman

def test_4(): assert to_roman(4) == 'IV'
def test_9(): assert to_roman(9) == 'IX'
def test_14(): assert to_roman(14) == 'XIV'
def test_40(): assert to_roman(40) == 'XL'
def test_58(): assert to_roman(58) == 'LVIII'
def test_90(): assert to_roman(90) == 'XC'
def test_1994(): assert to_roman(1994) == 'MCMXCIV'
