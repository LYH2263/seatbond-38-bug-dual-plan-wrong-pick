"""Contiguous seat bonding: aisle columns break runs; holds conflict on overlap.

Preview plans: leftmost contiguous block vs. best center-scored block."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeatCell:
    row: int
    col: int
    is_aisle: bool = False


@dataclass(frozen=True)
class HoldSpan:
    row: int
    start_col: int
    end_col: int  # inclusive


def contiguous_runs(row_cells: list[SeatCell]) -> list[tuple[int, int]]:
    """Return inclusive (start_col, end_col) runs of non-aisle seats, broken by aisles."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    prev_col: int | None = None
    for cell in sorted(row_cells, key=lambda c: c.col):
        if cell.is_aisle:
            if start is not None and prev_col is not None:
                runs.append((start, prev_col))
            start = None
            prev_col = None
            continue
        if start is None:
            start = cell.col
        elif prev_col is not None and cell.col != prev_col + 1:
            runs.append((start, prev_col))
            start = cell.col
        prev_col = cell.col
    if start is not None and prev_col is not None:
        runs.append((start, prev_col))
    return runs


def occupied_cols(holds: list[HoldSpan], row: int) -> set[int]:
    cols: set[int] = set()
    for h in holds:
        if h.row != row:
            continue
        for c in range(h.start_col, h.end_col + 1):
            cols.add(c)
    return cols


def free_segments(row_cells: list[SeatCell], holds: list[HoldSpan], row: int) -> list[tuple[int, int]]:
    """Inclusive (start_col, end_col) runs of empty non-aisle seats in one row."""
    taken = occupied_cols(holds, row)
    segs: list[tuple[int, int]] = []
    for start, end in contiguous_runs(row_cells):
        # a run may have holes if holds punched its middle — rebuild consecutive segments
        seg_start: int | None = None
        prev: int | None = None
        for col in range(start, end + 1):
            if col in taken:
                if seg_start is not None and prev is not None:
                    segs.append((seg_start, prev))
                seg_start = None
                prev = None
                continue
            if seg_start is None:
                seg_start = col
            prev = col
        if seg_start is not None and prev is not None:
            segs.append((seg_start, prev))
    return segs


def find_contiguous_block(
    row_cells: list[SeatCell],
    holds: list[HoldSpan],
    row: int,
    party_size: int,
) -> HoldSpan | None:
    """Find leftmost contiguous empty seats of party_size in a row."""
    if party_size <= 0:
        return None
    for seg_start, seg_end in free_segments(row_cells, holds, row):
        if seg_end - seg_start + 1 >= party_size:
            return HoldSpan(row=row, start_col=seg_start, end_col=seg_start + party_size - 1)
    return None


def all_feasible_spans(
    seats_by_row: dict[int, list[SeatCell]],
    holds: list[HoldSpan],
    party_size: int,
) -> list[HoldSpan]:
    """Every contiguous empty block of exactly party_size, rows ascending then start col."""
    if party_size <= 0:
        return []
    spans: list[HoldSpan] = []
    for row in sorted(seats_by_row.keys()):
        for seg_start, seg_end in free_segments(seats_by_row[row], holds, row):
            for start_col in range(seg_start, seg_end - party_size + 2):
                spans.append(
                    HoldSpan(row=row, start_col=start_col, end_col=start_col + party_size - 1)
                )
    return spans


def distance_to_center(span: HoldSpan, total_cols: int) -> float:
    """Distance in columns from the span midpoint to the hall centerline."""
    center = (total_cols + 1) / 2
    mid = (span.start_col + span.end_col) / 2
    return abs(mid - center)


def center_score(span: HoldSpan, total_cols: int) -> float:
    """0-100: the closer the span midpoint sits to the hall centerline, the higher the score."""
    max_dist = (total_cols - 1) / 2
    if max_dist <= 0:
        return 100.0
    return 100.0 * (1.0 - distance_to_center(span, total_cols) / max_dist)


def best_center_span(
    seats_by_row: dict[int, list[SeatCell]],
    holds: list[HoldSpan],
    party_size: int,
    total_cols: int,
) -> HoldSpan | None:
    """Highest center score wins; ties break on lower row number, then lower start col."""
    spans = all_feasible_spans(seats_by_row, holds, party_size)
    if not spans:
        return None
    return min(spans, key=lambda s: (-center_score(s, total_cols), s.row, s.start_col))


def find_bond_across_rows(
    seats_by_row: dict[int, list[SeatCell]],
    holds: list[HoldSpan],
    party_size: int,
) -> HoldSpan | None:
    for row in sorted(seats_by_row.keys()):
        block = find_contiguous_block(seats_by_row[row], holds, row, party_size)
        if block is not None:
            return block
    return None


def conflicts_with(existing: list[HoldSpan], candidate: HoldSpan) -> list[HoldSpan]:
    hits: list[HoldSpan] = []
    for h in existing:
        if h.row != candidate.row:
            continue
        if h.end_col < candidate.start_col or candidate.end_col < h.start_col:
            continue
        hits.append(h)
    return hits
