from app.services.bond_engine import (
    HoldSpan,
    SeatCell,
    all_feasible_spans,
    best_center_span,
    center_score,
    conflicts_with,
    contiguous_runs,
    distance_to_center,
    find_bond_across_rows,
    find_contiguous_block,
)


def _row(cols, aisles=()):
    return [SeatCell(row=1, col=c, is_aisle=(c in aisles)) for c in cols]


def test_aisle_breaks_runs():
    cells = _row(range(1, 11), aisles={5, 6})
    assert contiguous_runs(cells) == [(1, 4), (7, 10)]


def test_find_contiguous_skips_occupied():
    cells = _row(range(1, 9))
    holds = [HoldSpan(row=1, start_col=2, end_col=3)]
    block = find_contiguous_block(cells, holds, 1, 3)
    assert block == HoldSpan(row=1, start_col=4, end_col=6)


def test_party_too_large_returns_none():
    cells = _row(range(1, 5), aisles={3})
    assert find_contiguous_block(cells, [], 1, 3) is None


def test_conflict_overlap():
    existing = [HoldSpan(row=2, start_col=4, end_col=6)]
    cand = HoldSpan(row=2, start_col=6, end_col=8)
    assert conflicts_with(existing, cand) == existing


def test_find_across_rows():
    seats = {
        1: _row(range(1, 5)),
        2: [SeatCell(row=2, col=c) for c in range(1, 9)],
    }
    holds = [HoldSpan(row=1, start_col=1, end_col=4)]
    block = find_bond_across_rows(seats, holds, 4)
    assert block == HoldSpan(row=2, start_col=1, end_col=4)


def test_all_feasible_spans_enumerates_windows():
    seats = {1: _row(range(1, 6), aisles={3})}
    spans = all_feasible_spans(seats, [], 2)
    assert spans == [
        HoldSpan(row=1, start_col=1, end_col=2),
        HoldSpan(row=1, start_col=4, end_col=5),
    ]


def test_center_score_closer_midpoint_scores_higher():
    near = HoldSpan(row=1, start_col=5, end_col=7)  # midpoint 6
    far = HoldSpan(row=1, start_col=1, end_col=3)  # midpoint 2
    assert distance_to_center(near, 11) == 0.0
    assert center_score(near, 11) > center_score(far, 11)


def test_best_center_span_picks_middle():
    seats = {1: _row(range(1, 11))}
    span = best_center_span(seats, [], 2, 10)
    assert span == HoldSpan(row=1, start_col=5, end_col=6)  # midpoint 5.5 == hall center


def test_best_center_span_tie_breaks_by_row():
    seats = {
        1: _row(range(1, 11)),
        2: [SeatCell(row=2, col=c) for c in range(1, 11)],
    }
    span = best_center_span(seats, [], 2, 10)
    assert span == HoldSpan(row=1, start_col=5, end_col=6)


def test_best_center_span_tie_breaks_by_start_col():
    # middle blocked: equidistant windows on both sides -> lower start col wins
    cells = _row(range(1, 11))
    holds = [HoldSpan(row=1, start_col=5, end_col=6)]
    span = best_center_span({1: cells}, holds, 2, 10)
    assert span == HoldSpan(row=1, start_col=3, end_col=4)


def test_best_center_span_none_when_no_room():
    seats = {1: _row(range(1, 5), aisles={3})}
    assert best_center_span(seats, [], 3, 4) is None
