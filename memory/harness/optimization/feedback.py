"""Label only consistent all-metric improvement or deterioration."""


def label_change(before, after):
    if set(before) != set(after):
        return None
    changes = [after[k] - before[k] for k in before]
    if changes and all(v > 0 for v in changes):
        return "pos"
    if changes and all(v < 0 for v in changes):
        return "neg"
    return None
