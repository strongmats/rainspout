"""Tutorial 2's science, verbatim — module-level, testable with no skeleton."""


def smooth(values: list[float], window_len: int, method: str) -> list[float]:
    if not values or not all(isinstance(v, float) for v in values):
        raise ValueError("expected a non-empty list of floats")
    half = window_len // 2
    out = []
    for i in range(len(values)):
        window = values[max(0, i - half) : i + half + 1]
        out.append(
            sorted(window)[len(window) // 2]
            if method == "median"
            else sum(window) / len(window)
        )
    return out
