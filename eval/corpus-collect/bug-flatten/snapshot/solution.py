def flatten(d, prefix=''):
    out = {}
    for k, v in d.items():
        key = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, prefix))  # BUG: drops the new key
        else:
            out[key] = v
    return out
