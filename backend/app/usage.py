"""Records every search (search_events) and reports on app usage.

Searches on the website (/search/bioprojects) and through the public API
(/v1/projects, /v1/projects/{accession}) call record() from a FastAPI
background task, after the response is sent, so recording never slows a
search down and a failure to record never fails one. The admin usage page
(/admin/usage, see admin.py) reads the reports below.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import Integer, cast, desc, func, select, text
from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .rate_limit import client_ip

logger = logging.getLogger(__name__)

E = models.SearchEvent

Source = Literal["site", "api"]
Period = Literal["day", "week", "month"]

# Query parameters that aren't filters, so they're not kept in the filters column.
NOT_FILTERS = {"q", "sort", "limit", "offset"}


def set_filters(params: BaseModel) -> dict[str, Any]:
    """The filters a request set, as JSON: lists that aren't empty and
    values that aren't None, without paging or sorting."""
    out: dict[str, Any] = {}
    for name, value in params.model_dump(mode="json").items():
        if name in NOT_FILTERS or value is None or value == []:
            continue
        out[name] = value
    return out


def record(
    background: BackgroundTasks,
    request: Request,
    *,
    source: Source,
    params: Optional[BaseModel] = None,
    kind: str = "search",
    query: Optional[str] = None,
    total: Optional[int] = None,
    started: Optional[float] = None,
) -> None:
    """Queue the search to be written after the response is sent."""
    duration_ms = None if started is None else int((time.perf_counter() - started) * 1000)
    row = E(
        source=source,
        kind=kind,
        query=(query or "").strip()[:1000] or None,
        filters=set_filters(params) if params is not None else None,
        sort=getattr(params, "sort", None),
        offset=getattr(params, "offset", 0) or 0,
        total=total,
        duration_ms=duration_ms,
        client_ip=client_ip(request),
        visitor=(request.headers.get("x-visitor-id") or "")[:64] or None,
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    background.add_task(_insert, row)


def _insert(row: models.SearchEvent) -> None:
    try:
        with SessionLocal() as db:
            db.add(row)
            db.commit()
    except Exception:  # noqa: BLE001 - recording must never break anything
        logger.exception("Could not record search event")


# --- Reports for the admin page --------------------------------------------

# A visitor is the browser id when there is one, else the client IP.
VISITOR = func.coalesce(E.visitor, E.client_ip)


def _since(days: Optional[int]):
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _base(stmt, days: Optional[int], source: Optional[str]):
    since = _since(days)
    if since is not None:
        stmt = stmt.where(E.created_at >= since)
    if source:
        stmt = stmt.where(E.source == source)
    return stmt


def summary(db: Session, days: Optional[int], source: Optional[str]) -> dict:
    """Totals for the period: searches, visitors, and the same for today, this
    week and this month, so the page can open with the headline numbers."""
    def counts(**kw):
        stmt = _base(select(
            func.count().label("events"),
            func.count().filter(E.offset == 0).label("searches"),
            func.count(func.distinct(VISITOR)).label("visitors"),
            func.count().filter(E.source == "site").label("site"),
            func.count().filter(E.source == "api").label("api"),
            func.count().filter(E.query.is_not(None), E.offset == 0).label("with_text"),
            func.count().filter(E.total == 0, E.offset == 0).label("no_results"),
        ).select_from(E), kw.get("days"), source)
        return db.execute(stmt).mappings().one()

    first = db.scalar(_base(select(func.min(E.created_at)), None, source))
    last = db.scalar(_base(select(func.max(E.created_at)), None, source))
    return {
        "period": dict(counts(days=days)),
        "today": dict(counts(days=1)),
        "week": dict(counts(days=7)),
        "month": dict(counts(days=30)),
        "first_event": first.isoformat() if first else None,
        "last_event": last.isoformat() if last else None,
    }


def series(db: Session, period: Period, days: Optional[int], source: Optional[str]) -> list[dict]:
    """Searches and distinct visitors per day, week or month, oldest first.
    Periods without a search are left out (the page fills them with zeros)."""
    bucket = func.date_trunc(period, E.created_at).label("bucket")
    stmt = _base(
        select(
            bucket,
            func.count().filter(E.offset == 0).label("searches"),
            func.count().label("events"),
            func.count(func.distinct(VISITOR)).label("visitors"),
            func.count().filter(E.source == "site", E.offset == 0).label("site"),
            func.count().filter(E.source == "api", E.offset == 0).label("api"),
        ).select_from(E),
        days,
        source,
    ).group_by(bucket).order_by(bucket)
    return [
        {**dict(r), "bucket": r["bucket"].date().isoformat()}
        for r in db.execute(stmt).mappings()
    ]


def by_hour(db: Session, days: Optional[int], source: Optional[str]) -> list[dict]:
    """Searches per hour of the day (UTC)."""
    hour = cast(func.extract("hour", E.created_at), Integer).label("hour")
    stmt = _base(select(hour, func.count().label("searches")).select_from(E).where(E.offset == 0), days, source)
    rows = {r["hour"]: r["searches"] for r in db.execute(stmt.group_by(hour)).mappings()}
    return [{"hour": h, "searches": rows.get(h, 0)} for h in range(24)]


def top_queries(db: Session, days: Optional[int], source: Optional[str], limit: int) -> list[dict]:
    """The most searched texts, case-insensitively, newest search last."""
    q = func.lower(func.trim(E.query)).label("query")
    stmt = _base(
        select(
            q,
            func.count().label("searches"),
            func.count(func.distinct(VISITOR)).label("visitors"),
            func.max(E.created_at).label("last"),
            func.max(E.total).label("total"),
        ).select_from(E).where(E.query.is_not(None), E.offset == 0),
        days,
        source,
    ).group_by(q).order_by(desc("searches"), desc("last")).limit(limit)
    return [{**dict(r), "last": r["last"].isoformat()} for r in db.execute(stmt).mappings()]


def top_filters(db: Session, days: Optional[int], source: Optional[str], limit: int) -> dict:
    """Which filters are used (per field), and the most used values."""
    pair = func.jsonb_each(E.filters).table_valued("key", "value").render_derived("f")
    field_stmt = _base(
        select(pair.c.key.label("field"), func.count().label("searches"))
        .select_from(E)
        .join(pair, text("true"))
        .where(E.offset == 0),
        days,
        source,
    ).group_by(pair.c.key).order_by(desc("searches")).limit(limit)
    fields = [dict(r) for r in db.execute(field_stmt).mappings()]

    # Values of list filters: each value of each array, as text.
    value = func.jsonb_array_elements_text(pair.c.value).table_valued("value").render_derived("v")
    value_stmt = _base(
        select(pair.c.key.label("field"), value.c.value.label("value"), func.count().label("searches"))
        .select_from(E)
        .join(pair, text("true"))
        .join(value, text("true"))
        .where(E.offset == 0, func.jsonb_typeof(pair.c.value) == "array"),
        days,
        source,
    ).group_by(pair.c.key, value.c.value).order_by(desc("searches")).limit(limit)
    values = [dict(r) for r in db.execute(value_stmt).mappings()]
    return {"fields": fields, "values": values}


def recent(db: Session, days: Optional[int], source: Optional[str], limit: int, offset: int) -> dict:
    """The latest searches, newest first, with how many there are."""
    where = _base(select(E).where(E.offset == 0), days, source)
    total = db.scalar(select(func.count()).select_from(where.subquery()))
    rows = db.scalars(where.order_by(E.created_at.desc(), E.id.desc()).limit(limit).offset(offset)).all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat(),
                "source": r.source,
                "kind": r.kind,
                "query": r.query,
                "filters": r.filters or {},
                "sort": r.sort,
                "total": r.total,
                "duration_ms": r.duration_ms,
                "visitor": r.visitor or r.client_ip,
                "client_ip": r.client_ip,
                "user_agent": r.user_agent,
            }
            for r in rows
        ],
    }


def visitors(db: Session, days: Optional[int], source: Optional[str], limit: int) -> list[dict]:
    """The most active visitors."""
    v = VISITOR.label("visitor")
    stmt = _base(
        select(
            v,
            func.count().filter(E.offset == 0).label("searches"),
            func.min(E.created_at).label("first"),
            func.max(E.created_at).label("last"),
            func.max(E.client_ip).label("client_ip"),
            func.count(func.distinct(func.date(E.created_at))).label("days"),
        ).select_from(E),
        days,
        source,
    ).group_by(v).order_by(desc("searches")).limit(limit)
    return [
        {**dict(r), "first": r["first"].isoformat(), "last": r["last"].isoformat()}
        for r in db.execute(stmt).mappings()
    ]
