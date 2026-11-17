"""Endpoints for the admin pages: data normalisation (/admin/normalize)
and app usage (/admin/usage).

They change the database, so every request must carry the admin code in the
X-Admin-Code header. The code is the ADMIN_CODE environment variable (never
in the source); when it isn't set, the admin endpoints are disabled. There is
no login: the page asks for the code once and sends it with each request. The code is never stored or logged by the API.
Left out of the OpenAPI docs on purpose.
"""

import os
import secrets
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import normalize, usage
from .database import get_db


# From the environment (backend/.env in production, not in git). Unset or
# empty disables the admin pages.
ADMIN_CODE = os.getenv("ADMIN_CODE", "")


def require_admin(x_admin_code: Optional[str] = Header(default=None)) -> None:
    expected = ADMIN_CODE
    if not expected:
        raise HTTPException(status_code=503, detail="The admin pages are disabled (ADMIN_CODE is not set).")
    if not x_admin_code or not secrets.compare_digest(x_admin_code.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Wrong admin code.")


router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)], include_in_schema=False,
)

FieldName = Literal[tuple(normalize.FIELDS)]  # type: ignore[valid-type]


class FieldInfo(BaseModel):
    name: str
    label: str
    kind: str
    counts: str  # what the counts are: projects, studies
    rows: str  # what "rows changed" are


class ValueCount(BaseModel):
    value: str
    count: int


class ValueList(BaseModel):
    total: int
    items: list[ValueCount]


class Rule(BaseModel):
    id: int
    field: str
    action: str  # rename, capitalize
    from_value: str
    to_value: str
    rows: Optional[int] = None
    created_at: Optional[str] = None


class Job(BaseModel):
    id: str
    kind: str
    field: Optional[str] = None
    from_values: list[str]
    to_value: Optional[str] = None
    status: str
    rows: int
    refreshed: list[str]
    message: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RenameRequest(BaseModel):
    field: FieldName
    from_values: list[str] = Field(min_length=1, max_length=200)
    to_value: str = Field(min_length=1, max_length=500)


@router.get("/fields", response_model=list[FieldInfo])
def fields():
    return [
        {"name": name, "label": spec["label"], "kind": spec["kind"], "counts": spec["counts"],
         "rows": normalize.ROW_NAMES[spec["kind"]]}
        for name, spec in normalize.FIELDS.items()
    ]


@router.get("/values", response_model=ValueList)
def values(
    field: FieldName,
    q: str = "",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        return normalize.list_values(field, q.strip(), limit, offset)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/rules", response_model=list[Rule])
def rules(field: Optional[FieldName] = None):
    return normalize.list_rules(field)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    if not normalize.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="No such rule.")
    return {"deleted": rule_id}


@router.post("/rename", response_model=Job)
def rename(body: RenameRequest):
    to_value = body.to_value.strip()
    from_values = list(dict.fromkeys(v for v in body.from_values if v.strip()))
    if not to_value or not from_values:
        raise HTTPException(status_code=422, detail="Both the values to change and the new value are needed.")
    if to_value in from_values:
        raise HTTPException(status_code=422, detail="The new value is one of the values being changed.")
    return normalize.submit_rename(body.field, from_values, to_value).to_dict()


class CapitalizeRequest(BaseModel):
    field: FieldName


@router.post("/capitalize", response_model=Job)
def capitalize(body: CapitalizeRequest):
    return normalize.submit_capitalize(body.field).to_dict()


@router.post("/apply", response_model=Job)
def apply():
    return normalize.submit_apply().to_dict()


@router.get("/jobs", response_model=list[Job])
def jobs():
    return normalize.list_jobs()


# --- App usage (usage.py) ----------------------------------------------------

# How far back to look: a number of days, or 0 for everything.
Days = Annotated[int, Query(ge=0)]
UsageSource = Optional[Literal["site", "api"]]


def _days(days: int) -> Optional[int]:
    return days or None


@router.get("/usage/summary")
def usage_summary(days: Days = 30, source: UsageSource = None, db: Session = Depends(get_db)):
    return usage.summary(db, _days(days), source)


@router.get("/usage/series")
def usage_series(
    period: Literal["day", "week", "month"] = "day",
    days: Days = 30,
    source: UsageSource = None,
    db: Session = Depends(get_db),
):
    return usage.series(db, period, _days(days), source)


@router.get("/usage/hours")
def usage_hours(days: Days = 30, source: UsageSource = None, db: Session = Depends(get_db)):
    return usage.by_hour(db, _days(days), source)


@router.get("/usage/queries")
def usage_queries(
    days: Days = 30, source: UsageSource = None, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
):
    return usage.top_queries(db, _days(days), source, limit)


@router.get("/usage/filters")
def usage_filters(
    days: Days = 30, source: UsageSource = None, limit: int = Query(30, ge=1, le=500), db: Session = Depends(get_db),
):
    return usage.top_filters(db, _days(days), source, limit)


@router.get("/usage/recent")
def usage_recent(
    days: Days = 30,
    source: UsageSource = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return usage.recent(db, _days(days), source, limit, offset)


@router.get("/usage/visitors")
def usage_visitors(
    days: Days = 30, source: UsageSource = None, limit: int = Query(30, ge=1, le=500), db: Session = Depends(get_db),
):
    return usage.visitors(db, _days(days), source, limit)
