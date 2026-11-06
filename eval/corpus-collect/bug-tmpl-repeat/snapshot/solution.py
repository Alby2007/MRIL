def render(template, values):
    for k, v in values.items():
        template = template.replace('{' + k + '}', str(v), 1)  # BUG: first only
    return template
