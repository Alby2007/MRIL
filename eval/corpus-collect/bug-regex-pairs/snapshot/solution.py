import re


def pairs(text):
    m = re.search(r'(\w+)=(\w+)', text)   # BUG: first match only
    return [m.groups()] if m else []
