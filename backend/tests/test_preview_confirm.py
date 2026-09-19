"""Dual-plan preview + confirm flow: one confirm lands exactly one hold."""

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")  # app engine is unused; get_db is overridden

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Hall, PreviewToken, SeatHold, Showtime

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture()
def showtime():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = TestingSessionLocal()
    hall = Hall(name="测试厅", rows=8, cols=12, aisle_cols="5,6")
    session.add(hall)
    session.flush()
    st = Showtime(hall_id=hall.id, film_title="测试片", start_at=datetime(2026, 9, 18, 20, 0))
    session.add(st)
    session.commit()
    yield session, st
    session.close()


def _preview(showtime_id: int, party_size: int = 3, **extra):
    r = client.post(
        "/api/holds/preview",
        json={"showtime_id": showtime_id, "party_size": party_size, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(token: str, plan_id: str):
    return client.post("/api/holds/confirm", json={"token": token, "plan_id": plan_id})


def _holds(showtime_id: int):
    r = client.get("/api/holds")
    assert r.status_code == 200
    return [h for h in r.json() if h["showtime_id"] == showtime_id]


def test_preview_returns_two_distinct_plans(showtime):
    _, st = showtime
    data = _preview(st.id, 3)
    assert data["merged"] is False
    assert data["token"]
    assert data["ttl_seconds"] > 0
    assert len(data["plans"]) == 2
    left, center = data["plans"]
    assert left["plan_id"] == "leftmost"
    assert center["plan_id"] == "center"
    # 8x12 hall, aisles 5-6: leftmost hugs row 1 left edge, center plan hugs the centerline
    assert (left["row"], left["start_col"], left["end_col"]) == (1, 1, 3)
    assert (center["row"], center["start_col"], center["end_col"]) == (1, 7, 9)
    assert center["score"] > left["score"]
    assert center["distance_to_center"] < left["distance_to_center"]


def test_confirm_persists_only_the_selected_plan(showtime):
    _, st = showtime
    data = _preview(st.id, 3)
    r = _confirm(data["token"], "center")
    assert r.status_code == 200, r.text
    hold = r.json()
    assert (hold["row"], hold["start_col"], hold["end_col"]) == (1, 7, 9)
    holds = _holds(st.id)
    assert len(holds) == 1
    assert (holds[0]["row"], holds[0]["start_col"], holds[0]["end_col"]) == (1, 7, 9)


def test_cancel_creates_no_hold(showtime):
    _, st = showtime
    data = _preview(st.id, 3)
    r = client.post("/api/holds/cancel", json={"token": data["token"]})
    assert r.status_code == 200
    assert _holds(st.id) == []
    # a cancelled token can no longer be confirmed
    r = _confirm(data["token"], "leftmost")
    assert r.status_code == 409
    assert "重新试算" in r.json()["detail"]
    assert _holds(st.id) == []


def test_confirm_fails_when_occupancy_changed(showtime):
    session, st = showtime
    data = _preview(st.id, 3)
    # interfering occupancy lands after the preview
    session.add(
        SeatHold(showtime_id=st.id, order_code="SB-INTF", row=1, start_col=7, end_col=9, party_size=3)
    )
    session.commit()
    r = _confirm(data["token"], "center")
    assert r.status_code == 409
    assert "重新试算" in r.json()["detail"]
    holds = _holds(st.id)
    assert len(holds) == 1
    assert holds[0]["order_code"] == "SB-INTF"


def test_single_confirm_writes_exactly_one_hold(showtime):
    _, st = showtime
    data = _preview(st.id, 3)
    r1 = _confirm(data["token"], "leftmost")
    assert r1.status_code == 200, r1.text
    assert len(_holds(st.id)) == 1
    # same token again — even naming the other plan — must not write a second hold
    r2 = _confirm(data["token"], "center")
    assert r2.status_code == 409
    assert "重新试算" in r2.json()["detail"]
    holds = _holds(st.id)
    assert len(holds) == 1
    assert (holds[0]["row"], holds[0]["start_col"], holds[0]["end_col"]) == (1, 1, 3)


def test_expired_token_rejected(showtime):
    session, st = showtime
    data = _preview(st.id, 3)
    tok = session.scalar(select(PreviewToken).where(PreviewToken.token == data["token"]))
    tok.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()
    r = _confirm(data["token"], "leftmost")
    assert r.status_code == 409
    assert "重新试算" in r.json()["detail"]
    assert _holds(st.id) == []


def test_merged_when_both_strategies_agree(showtime):
    session, _ = showtime
    hall = Hall(name="小厅", rows=2, cols=5, aisle_cols="")
    session.add(hall)
    session.flush()
    st = Showtime(hall_id=hall.id, film_title="包场", start_at=datetime(2026, 9, 18, 22, 0))
    session.add(st)
    session.commit()
    data = _preview(st.id, 5)
    assert data["merged"] is True
    assert len(data["plans"]) == 1
    plan = data["plans"][0]
    assert (plan["row"], plan["start_col"], plan["end_col"]) == (1, 1, 5)
    r = _confirm(data["token"], plan["plan_id"])
    assert r.status_code == 200, r.text
    assert len(_holds(st.id)) == 1


def test_confirm_unknown_plan_rejected(showtime):
    _, st = showtime
    data = _preview(st.id, 3)
    r = _confirm(data["token"], "nope")
    assert r.status_code == 400
    assert _holds(st.id) == []


def test_preview_without_seats_conflicts(showtime):
    _, st = showtime
    # longest aisle-bounded run is 6 seats (cols 7-12); a party of 7 fits nowhere
    r = client.post("/api/holds/preview", json={"showtime_id": st.id, "party_size": 7})
    assert r.status_code == 409
