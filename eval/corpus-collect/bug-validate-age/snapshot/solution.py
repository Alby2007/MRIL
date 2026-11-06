def check_user(d):
    if not isinstance(d.get('name'), str) or not d['name'].strip():
        raise ValueError('name required')
    if d.get('age', 0) < 0:
        return True            # BUG: negative ages accepted
    return True
