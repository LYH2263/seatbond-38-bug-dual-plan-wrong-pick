import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import ConflictLog, Hall, PreviewToken, SeatHold, Showtime
from app.schemas.schemas import (
    CancelRequest,
    ConfirmRequest,
    ConflictOut,
    HallOut,
    HoldOut,
    HoldRequest,
    PlanOut,
    PreviewRequest,
    PreviewResponse,
    SeatMapCell,
    SeatMapOut,
    ShowtimeOut,
)
from app.services.bond_engine import (
    HoldSpan,
    SeatCell,
    best_center_span,
    center_score,
    conflicts_with,
    distance_to_center,
    find_bond_across_rows,
    find_contiguous_block,
)

api_router = APIRouter()


def _aisles(hall: Hall) -> list[int]:
    if not hall.aisle_cols.strip():
        return []
    return [int(x) for x in hall.aisle_cols.split(",") if x.strip()]


def _hall_out(h: Hall) -> HallOut:
    return HallOut(id=h.id, name=h.name, rows=h.rows, cols=h.cols, aisle_cols=_aisles(h))


def _seats_by_row(hall: Hall) -> dict[int, list[SeatCell]]:
    aisles = set(_aisles(hall))
    return {
        r: [SeatCell(row=r, col=c, is_aisle=c in aisles) for c in range(1, hall.cols + 1)]
        for r in range(1, hall.rows + 1)
    }


def _spans(holds: list[SeatHold]) -> list[HoldSpan]:
    return [HoldSpan(row=h.row, start_col=h.start_col, end_col=h.end_col) for h in holds]


def _fingerprint(holds: list[SeatHold]) -> str:
    """Hash of the showtime's current occupancy; any change invalidates a preview."""
    spans = sorted((h.row, h.start_col, h.end_col) for h in holds)
    return hashlib.sha256(json.dumps(spans, separators=(",", ":")).encode()).hexdigest()


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/halls", response_model=list[HallOut])
def list_halls(db: Session = Depends(get_db)):
    return [_hall_out(h) for h in db.scalars(select(Hall).order_by(Hall.id)).all()]


@api_router.get("/showtimes", response_model=list[ShowtimeOut])
def list_showtimes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Showtime).order_by(Showtime.start_at)).all()
    out = []
    for s in rows:
        hall = db.get(Hall, s.hall_id)
        out.append(
            ShowtimeOut(
                id=s.id,
                hall_id=s.hall_id,
                film_title=s.film_title,
                start_at=s.start_at,
                hall_name=hall.name if hall else None,
            )
        )
    return out


@api_router.get("/seatmap/{showtime_id}", response_model=SeatMapOut)
def seatmap(showtime_id: int, db: Session = Depends(get_db)):
    st = db.get(Showtime, showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    aisles = set(_aisles(hall))
    holds = db.scalars(select(SeatHold).where(SeatHold.showtime_id == showtime_id)).all()
    occupied: set[tuple[int, int]] = set()
    for h in holds:
        for c in range(h.start_col, h.end_col + 1):
            occupied.add((h.row, c))
    cells: list[SeatMapCell] = []
    total = hall.rows * hall.cols
    for r in range(1, hall.rows + 1):
        for c in range(1, hall.cols + 1):
            occ = (r, c) in occupied
            cells.append(
                SeatMapCell(
                    row=r,
                    col=c,
                    is_aisle=c in aisles,
                    occupied=occ,
                    heat=1.0 if occ else (0.15 if c in aisles else 0.0),
                )
            )
    return SeatMapOut(
        showtime_id=showtime_id,
        hall_name=hall.name,
        rows=hall.rows,
        cols=hall.cols,
        cells=cells,
    )


@api_router.get("/holds", response_model=list[HoldOut])
def list_holds(db: Session = Depends(get_db)):
    return db.scalars(select(SeatHold).order_by(SeatHold.id.desc())).all()


@api_router.get("/conflicts", response_model=list[ConflictOut])
def list_conflicts(db: Session = Depends(get_db)):
    return db.scalars(select(ConflictLog).order_by(ConflictLog.id.desc())).all()


@api_router.post("/holds", response_model=HoldOut)
def create_hold(body: HoldRequest, db: Session = Depends(get_db)):
    st = db.get(Showtime, body.showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    existing = db.scalars(select(SeatHold).where(SeatHold.showtime_id == body.showtime_id)).all()
    holds = _spans(existing)
    seats_by_row = _seats_by_row(hall)

    block = None
    if body.preferred_row:
        block = find_contiguous_block(
            seats_by_row.get(body.preferred_row, []), holds, body.preferred_row, body.party_size
        )
    if block is None:
        block = find_bond_across_rows(seats_by_row, holds, body.party_size)
    if block is None:
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=f"无足够连续空座（人数 {body.party_size}）",
            )
        )
        db.commit()
        raise HTTPException(409, "无足够连续空座")

    hits = conflicts_with(holds, block)
    if hits:
        db.add(
            ConflictLog(
                showtime_id=body.showtime_id,
                party_size=body.party_size,
                reason=f"与既有持座重叠：第{hits[0].row}排 {hits[0].start_col}-{hits[0].end_col}",
            )
        )
        db.commit()
        raise HTTPException(409, "与既有持座冲突")

    code = f"SB-{int(datetime.utcnow().timestamp()) % 100000:05d}"
    hold = SeatHold(
        showtime_id=body.showtime_id,
        order_code=code,
        row=block.row,
        start_col=block.start_col,
        end_col=block.end_col,
        party_size=body.party_size,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold


def _plan_out(plan_id: str, label: str, span: HoldSpan, total_cols: int) -> dict:
    return {
        "plan_id": plan_id,
        "label": label,
        "row": span.row,
        "start_col": span.start_col,
        "end_col": span.end_col,
        "score": round(center_score(span, total_cols), 1),
        "distance_to_center": distance_to_center(span, total_cols),
    }


@api_router.post("/holds/preview", response_model=PreviewResponse)
def preview_hold(body: PreviewRequest, db: Session = Depends(get_db)):
    """Trial-run both strategies; holds nothing. Returns a short-lived confirm token."""
    st = db.get(Showtime, body.showtime_id)
    if not st:
        raise HTTPException(404, "场次不存在")
    hall = db.get(Hall, st.hall_id)
    assert hall
    existing = db.scalars(select(SeatHold).where(SeatHold.showtime_id == body.showtime_id)).all()
    holds = _spans(existing)
    seats_by_row = _seats_by_row(hall)

    left = None
    if body.preferred_row:
        left = find_contiguous_block(
            seats_by_row.get(body.preferred_row, []), holds, body.preferred_row, body.party_size
        )
    if left is None:
        left = find_bond_across_rows(seats_by_row, holds, body.party_size)
    center = best_center_span(seats_by_row, holds, body.party_size, hall.cols)
    if left is None or center is None:
        raise HTTPException(409, "无足够连续空座")

    merged = (left.row, left.start_col, left.end_col) == (
        center.row,
        center.start_col,
        center.end_col,
    )
    if merged:
        plans = [_plan_out("leftmost", "最左连续 · 居中优选（方案一致）", left, hall.cols)]
    else:
        plans = [
            _plan_out("leftmost", "最左连续", left, hall.cols),
            _plan_out("center", "居中优选", center, hall.cols),
        ]

    now = datetime.utcnow()
    expires = now + timedelta(seconds=settings.preview_ttl_seconds)
    tok = PreviewToken(
        token=secrets.token_urlsafe(16),
        showtime_id=body.showtime_id,
        party_size=body.party_size,
        plans_json=json.dumps(plans),
        fingerprint=_fingerprint(existing),
        status="pending",
        created_at=now,
        expires_at=expires,
    )
    db.add(tok)
    db.commit()
    return PreviewResponse(
        token=tok.token,
        expires_at=expires,
        ttl_seconds=settings.preview_ttl_seconds,
        merged=merged,
        plans=[PlanOut(**p) for p in plans],
    )


@api_router.post("/holds/confirm", response_model=HoldOut)
def confirm_hold(body: ConfirmRequest, db: Session = Depends(get_db)):
    """Persist exactly the selected plan of a preview; rejects stale tokens/occupancy."""
    tok = db.scalar(select(PreviewToken).where(PreviewToken.token == body.token))
    if tok is None:
        raise HTTPException(404, "确认令牌无效，请重新试算")
    if tok.status == "cancelled":
        raise HTTPException(409, "该试算已取消，请重新试算")
    if tok.status == "confirmed":
        raise HTTPException(409, "该试算已确认过，请重新试算")
    if tok.expires_at <= datetime.utcnow():
        raise HTTPException(409, "试算已过期，请重新试算")
    existing = db.scalars(select(SeatHold).where(SeatHold.showtime_id == tok.showtime_id)).all()
    if _fingerprint(existing) != tok.fingerprint:
        raise HTTPException(409, "占用已变化，请重新试算")
    plans = json.loads(tok.plans_json)
    picked = next((p for p in plans if p["plan_id"] == body.plan_id), None)
    if picked is None:
        raise HTTPException(400, "所选方案不在本次试算中，请重新试算")
    span = HoldSpan(row=picked["row"], start_col=picked["start_col"], end_col=picked["end_col"])
    if conflicts_with(_spans(existing), span):
        raise HTTPException(409, "与既有持座冲突，请重新试算")

    # Atomically consume the token exactly once: only a pending row flips to confirmed.
    res = db.execute(
        update(PreviewToken)
        .where(PreviewToken.id == tok.id, PreviewToken.status == "pending")
        .values(status="confirmed")
    )
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "该试算已确认过，请重新试算")

    code = f"SB-{int(datetime.utcnow().timestamp()) % 100000:05d}"
    hold = SeatHold(
        showtime_id=tok.showtime_id,
        order_code=code,
        row=span.row,
        start_col=span.start_col,
        end_col=span.end_col,
        party_size=tok.party_size,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold


@api_router.post("/holds/cancel")
def cancel_preview(body: CancelRequest, db: Session = Depends(get_db)):
    """Abandon a preview; never holds seats. Idempotent."""
    tok = db.scalar(select(PreviewToken).where(PreviewToken.token == body.token))
    if tok is not None and tok.status == "pending":
        tok.status = "cancelled"
        db.commit()
    return {"ok": True}
