class Person:
    def __init__(self, name, age, city):
        self.name = name
        self.age = age
        self.city = city

    def __eq__(self, other):
        return (self.name, self.age, self.city) == (other.name, other.age, other.city)


def person_to_dict(p):
    return {'name': p.name, 'age': p.age}   # BUG: drops city


def dict_to_person(d):
    return Person(d['name'], d['age'], d.get('city'))
