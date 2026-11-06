def render(template, values):
    out, i = '', 0
    while i < len(template):
        if template[i:i + 2] == '{{':
            out += '{{'   # BUG: should emit a single literal {
            i += 2
        elif template[i:i + 2] == '}}':
            out += '}}'
            i += 2
        elif template[i] == '{':
            j = template.find('}', i)
            out += str(values[template[i + 1:j]])  # BUG: KeyError on absent key
            i = j + 1
        else:
            out += template[i]
            i += 1
    return out
