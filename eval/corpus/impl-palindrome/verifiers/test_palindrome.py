from solution import is_palindrome

def test_phrase(): assert is_palindrome('A man, a plan, a canal: Panama')
def test_negative(): assert not is_palindrome('hello world')
def test_empty(): assert is_palindrome('')
def test_case(): assert is_palindrome('RaceCar')
def test_digits(): assert is_palindrome('12321')
