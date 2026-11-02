from datetime import date, datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Bioproject(Base):
    __tablename__ = "bioprojects"
    __table_args__ = (
        Index("bioprojects_sra_study_idx", "sra_study"),
        Index("bioprojects_tax_id_idx", "tax_id"),
    )

    bioproject: Mapped[str] = mapped_column(Text, primary_key=True)
    sra_study: Mapped[str] = mapped_column(Text, primary_key=True)
    n_experiments: Mapped[Optional[int]]
    found_in_bioproject_xml: Mapped[Optional[bool]]
    bioproject_uid: Mapped[Optional[int]] = mapped_column(BigInteger)
    name: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    data_types: Mapped[Optional[str]] = mapped_column(Text)
    organism_name: Mapped[Optional[str]] = mapped_column(Text)
    tax_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    supergroup: Mapped[Optional[str]] = mapped_column(Text)
    target_material: Mapped[Optional[str]] = mapped_column(Text)
    target_capture: Mapped[Optional[str]] = mapped_column(Text)
    sample_scope: Mapped[Optional[str]] = mapped_column(Text)
    method_type: Mapped[Optional[str]] = mapped_column(Text)
    objectives: Mapped[Optional[str]] = mapped_column(Text)
    relevance: Mapped[Optional[str]] = mapped_column(Text)
    project_release_date: Mapped[Optional[date]]
    # Filled by backend/sql/release_date.sql; see there for how it's chosen.
    release_date: Mapped[Optional[date]]
    geo_accessions: Mapped[Optional[str]] = mapped_column(Text)
    center_ids: Mapped[Optional[Any]] = mapped_column(JSONB)
    external_links: Mapped[Optional[Any]] = mapped_column(JSONB)
    grants: Mapped[Optional[Any]] = mapped_column(JSONB)
    publication_count: Mapped[Optional[int]]
    pubmed_ids: Mapped[Optional[str]] = mapped_column(Text)
    first_publication_date: Mapped[Optional[date]]
    journals: Mapped[Optional[str]] = mapped_column(Text)
    publication_titles: Mapped[Optional[str]] = mapped_column(Text)
    publications: Mapped[Optional[Any]] = mapped_column(JSONB)
    submission_id: Mapped[Optional[str]] = mapped_column(Text)
    submitted_date: Mapped[Optional[date]]
    last_update_date: Mapped[Optional[date]]
    organization: Mapped[Optional[str]] = mapped_column(Text)
    organization_country: Mapped[Optional[str]] = mapped_column(Text)
    access: Mapped[Optional[str]] = mapped_column(Text)
    parent_projects: Mapped[Optional[str]] = mapped_column(Text)

    # Loaded with the project in one extra query per result list (selectin).
    tag_row: Mapped[Optional["BioprojectTags"]] = relationship(
        primaryjoin="foreign(BioprojectTags.bioproject) == Bioproject.bioproject",
        uselist=False,
        viewonly=True,
        lazy="selectin",
    )

    @property
    def tags(self) -> list[str]:
        """The project's tag words, most relevant first."""
        if self.tag_row is None:
            return []
        return [t for t in dict.fromkeys(self.tag_row.tags.split("; ")) if t.strip()]


class BioprojectTags(Base):
    """Tag words per bioproject: organisms, diseases, tissues, cell types, ...

    Loaded by Automations/TagWords/bioproject_tags_schema.sql. One row per
    bioproject; tags is a "; "-separated list, most relevant first.
    """

    __tablename__ = "bioproject_tags"

    bioproject: Mapped[str] = mapped_column(Text, primary_key=True)
    tags: Mapped[str] = mapped_column(Text, nullable=False)
    # Each tag's type (organism, disease, tissue, ...), "; "-separated in the
    # same order; NULL for rows tagged before types were kept. Deferred, so
    # loading a project's tags never reads it.
    labels: Mapped[Optional[str]] = mapped_column(Text, deferred=True)


class BioprojectAttributes(Base):
    """Sample attributes per bioproject, normalised from sra_metadata's jattr.

    Loaded by Automations/output/bioproject_attributes_schema.sql; built by
    Automations/jattr_normalize.py (docs/jattr-normalization.md). attributes
    holds n_runs and, per field (tissue, sex, cell_line, ...), a list of
    distinct values, most frequent first. The search filters read the
    bioproject_attribute_values view built from it.
    """

    __tablename__ = "bioproject_attributes"

    bioproject: Mapped[str] = mapped_column(Text, primary_key=True)
    attributes: Mapped[Any] = mapped_column(JSONB, nullable=False)


class ValueNormalization(Base):
    """A rename of a filter value, recorded by the admin normalisation page.

    Applied to the data when made, and again after every data load
    (backend/app/normalize.py), in id order. Never dropped by the data
    loading scripts, so the normalisation survives them.
    """

    __tablename__ = "value_normalizations"
    __table_args__ = (Index("value_normalizations_field_idx", "field"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    field: Mapped[str] = mapped_column(Text, nullable=False)  # a key of normalize.FIELDS
    # "rename" (from_value -> to_value) or "capitalize" (every value's first
    # letter; from_value and to_value are empty).
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default="rename")
    from_value: Mapped[str] = mapped_column(Text, nullable=False)
    to_value: Mapped[str] = mapped_column(Text, nullable=False)
    # Rows changed when the rule was made.
    rows: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BioprojectEmbedding(Base):
    __tablename__ = "bioproject_embeddings"
    __table_args__ = (
        Index(
            "bioproject_embeddings_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    bioproject: Mapped[str] = mapped_column(Text, primary_key=True)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False)


class SraMetadata(Base):
    """One row per SRA run (acc = SRR/ERR/DRR accession)."""

    __tablename__ = "sra_metadata"

    acc: Mapped[str] = mapped_column(Text, primary_key=True)
    assay_type: Mapped[Optional[str]] = mapped_column(Text)
    center_name: Mapped[Optional[str]] = mapped_column(Text)
    experiment: Mapped[Optional[str]] = mapped_column(Text, index=True)
    sample_name: Mapped[Optional[str]] = mapped_column(Text)
    instrument: Mapped[Optional[str]] = mapped_column(Text)
    librarylayout: Mapped[Optional[str]] = mapped_column(Text)
    libraryselection: Mapped[Optional[str]] = mapped_column(Text)
    librarysource: Mapped[Optional[str]] = mapped_column(Text)
    platform: Mapped[Optional[str]] = mapped_column(Text)
    sample_acc: Mapped[Optional[str]] = mapped_column(Text)
    biosample: Mapped[Optional[str]] = mapped_column(Text, index=True)
    organism: Mapped[Optional[str]] = mapped_column(Text, index=True)
    sra_study: Mapped[Optional[str]] = mapped_column(Text, index=True)
    releasedate: Mapped[Optional[date]]
    bioproject: Mapped[Optional[str]] = mapped_column(Text, index=True)
    library_name: Mapped[Optional[str]] = mapped_column(Text)
    geo_loc_name_country_calc: Mapped[Optional[str]] = mapped_column(Text)
