import re


def count_errors(text):
    return len(re.findall(r'^ERROR', text))  # BUG: ^ is whole-string start only
