from solution import Person, dict_to_person, person_to_dict


def test_roundtrip():
    p = Person('ada', 36, 'london')
    assert dict_to_person(person_to_dict(p)) == p


def test_all_fields_present():
    d = person_to_dict(Person('ada', 36, 'london'))
    assert d == {'name': 'ada', 'age': 36, 'city': 'london'}


def test_from_dict():
    p = dict_to_person({'name': 'bo', 'age': 9, 'city': 'oslo'})
    assert (p.name, p.age, p.city) == ('bo', 9, 'oslo')
