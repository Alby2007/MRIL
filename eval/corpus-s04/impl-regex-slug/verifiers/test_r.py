from solution import slugify


def test_basic():
    assert slugify('Hello World') == 'hello-world'


def test_underscores():
    assert slugify('a_b__c') == 'a-b-c'


def test_edge_hyphens_dropped():
    assert slugify('--x--') == 'x'


def test_special_chars_removed():
    assert slugify('Café! 2024') == 'caf-2024'


def test_collapse_runs():
    assert slugify('a   b___c') == 'a-b-c'
