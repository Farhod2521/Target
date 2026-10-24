from collections.abc import Sequence

from app.modules.metrics.selectors.shapes import Point, Series

TOP = 8.0
BOTTOM = 92.0


def series(
    *,
    key: str,
    label: str,
    values: Sequence[int | None],
    labels: Sequence[str],
    displays: Sequence[str],
    known: int | None = None,
) -> Series:
    step = 100 / (len(values) - 1) if len(values) > 1 else 0
    if known is not None:
        values, labels, displays = (values[:known], labels[:known], displays[:known])
    seen = [value for value in values if value is not None]
    low = min(seen) if seen else 0
    high = max(seen) if seen else 0
    span = high - low or 1
    points = tuple(
        (
            Point(
                x=round(index * step, 2),
                y=round(
                    BOTTOM
                    - ((value if value is not None else low) - low)
                    / span
                    * (BOTTOM - TOP),
                    2,
                ),
                label=labels[index],
                display=displays[index],
            )
            for index, value in enumerate(values)
        )
    )
    return Series(
        key=key,
        label=label,
        polyline=" ".join(f"{point.x},{point.y}" for point in points),
        points=points,
        peak=_display_of(high, values, displays),
        floor=_display_of(low, values, displays),
    )


def _display_of(
    value: int, values: Sequence[int | None], displays: Sequence[str]
) -> str:
    for index, candidate in enumerate(values):
        if candidate == value:
            return displays[index]
    return ""
