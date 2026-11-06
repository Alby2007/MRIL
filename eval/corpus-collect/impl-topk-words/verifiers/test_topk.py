from solution import top_k_words


def test_basic_order():
    assert top_k_words('b a a b c c c', 2) == ['c', 'a']


def test_ties_alphabetical():
    # all appear twice; alphabetical order breaks ties
    assert top_k_words('z y x z y x', 3) == ['x', 'y', 'z']


def test_k_larger_than_vocab():
    assert top_k_words('one two two', 5) == ['two', 'one']


def test_case_and_punctuation():
    out = top_k_words('Hello, hello! world. WORLD, hello', 2)
    assert out == ['hello', 'world']


def test_empty_text():
    assert top_k_words('', 3) == []


def test_single_word():
    assert top_k_words('solo', 1) == ['solo']
