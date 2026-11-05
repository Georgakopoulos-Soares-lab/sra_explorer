import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import admin, embeddings, models, normalize, public_api, schemas, search, search_summary, statistics
from .database import Base, engine, get_db

logger = logging.getLogger(__name__)


def check_release_date() -> None:
    """Warn when bioprojects lacks release_date, which reloading the table drops."""
    with engine.connect() as conn:
        exists_ = conn.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'bioprojects' AND column_name = 'release_date')"
        ))
    if not exists_:
        logger.error(
            "bioprojects.release_date is missing, so project queries will fail."
            " Run backend/sql/release_date.sql (after backend/sql/study_facets.sql)."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only creates tables that don't exist yet; never alters loaded data.
    Base.metadata.create_all(bind=engine)
    normalize.ensure_schema()
    check_release_date()
    threading.Thread(target=search.warm_cache, daemon=True).start()
    threading.Thread(target=statistics.refresh, daemon=True).start()
    threading.Thread(target=embeddings.warm_model, daemon=True).start()
    yield


app = FastAPI(title="SRAscout API", lifespan=lifespan)

# The Vite dev server proxies /api to this app, so CORS only matters when the
# frontend calls the API directly (e.g. VITE_API_BASE_URL=http://localhost:8000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    # POST and DELETE for the admin normalisation page (admin.py).
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(search_summary.router)
app.include_router(statistics.router)
app.include_router(public_api.router)
app.include_router(public_api.docs_router)
app.include_router(admin.router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/bioprojects", response_model=list[schemas.BioprojectOut])
def list_bioprojects(
    sra_study: Optional[str] = None,
    tax_id: Optional[int] = None,
    organism_name: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(models.Bioproject)
    if sra_study:
        stmt = stmt.where(models.Bioproject.sra_study == sra_study)
    if tax_id is not None:
        stmt = stmt.where(models.Bioproject.tax_id == tax_id)
    if organism_name:
        stmt = stmt.where(models.Bioproject.organism_name.ilike(f"%{organism_name}%"))
    stmt = stmt.order_by(models.Bioproject.bioproject, models.Bioproject.sra_study)
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@app.get("/bioprojects/{bioproject}", response_model=list[schemas.BioprojectOut])
def get_bioproject(bioproject: str, db: Session = Depends(get_db)):
    # A bioproject can map to several SRA studies (composite primary key).
    rows = db.scalars(
        select(models.Bioproject).where(models.Bioproject.bioproject == bioproject)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Bioproject not found")
    return rows


@app.get("/runs", response_model=list[schemas.SraMetadataOut])
def list_runs(
    bioproject: Optional[str] = None,
    sra_study: Optional[str] = None,
    experiment: Optional[str] = None,
    biosample: Optional[str] = None,
    organism: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(models.SraMetadata)
    filters = {
        "bioproject": bioproject,
        "sra_study": sra_study,
        "experiment": experiment,
        "biosample": biosample,
        "organism": organism,
    }
    for column, value in filters.items():
        if value:
            stmt = stmt.where(getattr(models.SraMetadata, column) == value)
    stmt = stmt.order_by(models.SraMetadata.acc)
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@app.get("/runs/{acc}", response_model=schemas.SraMetadataOut)
def get_run(acc: str, db: Session = Depends(get_db)):
    run = db.get(models.SraMetadata, acc)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
