"""
Build the `bioprojects` table for the SRA explorer database.

One row per (bioproject, sra_study) pair found in all_sra_experiments_metadata.tsv,
enriched with project-level metadata parsed from NCBI's bioproject.xml
(title, description, publications/journals, dates, organism, grants, ...).

Outputs (in Automations/output/):
  bioprojects.csv         -> data, PostgreSQL CSV format (multi-valued fields as JSON)
  bioprojects_schema.sql  -> CREATE TABLE + \\copy command for loading the CSV

Both input files are huge (~10 GB TSV, ~4 GB XML) so both are streamed.
"""

import csv
import html
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from lxml import etree

BASE_DIR = Path(__file__).resolve().parent
EXPERIMENTS_TSV = BASE_DIR / "output" / "all_sra_experiments_metadata.tsv"
BIOPROJECT_XML = BASE_DIR / "ENA" / "bioproject.xml"
OUT_CSV = BASE_DIR / "output" / "bioprojects.csv"
OUT_SQL = BASE_DIR / "output" / "bioprojects_schema.sql"

TABLE_NAME = "bioprojects"

# (column name, PostgreSQL type) — order defines the CSV column order
COLUMNS = [
    ("bioproject", "TEXT NOT NULL"),             # e.g. PRJNA656818
    ("sra_study", "TEXT NOT NULL"),              # e.g. SRP276958
    ("n_experiments", "INTEGER"),                # experiments of this pair in the experiments table
    ("found_in_bioproject_xml", "BOOLEAN"),
    ("bioproject_uid", "BIGINT"),                # NCBI numeric id
    ("name", "TEXT"),
    ("title", "TEXT"),
    ("description", "TEXT"),
    ("data_types", "TEXT"),                      # e.g. "Epigenomics; Transcriptome or Gene expression"
    ("organism_name", "TEXT"),
    ("tax_id", "BIGINT"),
    ("supergroup", "TEXT"),                      # Eukaryotes / Bacteria / ...
    ("target_material", "TEXT"),                 # Genome / Transcriptome / ...
    ("target_capture", "TEXT"),
    ("sample_scope", "TEXT"),
    ("method_type", "TEXT"),
    ("objectives", "TEXT"),
    ("relevance", "TEXT"),                       # e.g. "Medical; ModelOrganism"
    ("project_release_date", "DATE"),
    ("geo_accessions", "TEXT"),                  # e.g. "GSE156128"
    ("center_ids", "JSONB"),                     # [{"center": "GEO", "id": "GSE156128"}]
    ("external_links", "JSONB"),                 # [{"label", "category", "url" | "db", "id"}]
    ("grants", "JSONB"),                         # [{"grant_id", "title", "agency", "agency_abbr"}]
    ("publication_count", "INTEGER"),
    ("pubmed_ids", "TEXT"),                      # "; "-separated
    ("first_publication_date", "DATE"),
    ("journals", "TEXT"),                        # "; "-separated distinct journal titles
    ("publication_titles", "TEXT"),              # " || "-separated
    ("publications", "JSONB"),                   # full structured citations
    ("submission_id", "TEXT"),
    ("submitted_date", "DATE"),
    ("last_update_date", "DATE"),
    ("organization", "TEXT"),
    ("organization_country", "TEXT"),
    ("access", "TEXT"),
    ("parent_projects", "TEXT"),                 # umbrella projects (ProjectLinks), "; "-separated
]
COLUMN_NAMES = [c for c, _ in COLUMNS]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
ENUM_RE = re.compile(r"^e(?=[A-Z])")  # NCBI enums: eGenome -> Genome


# ---------------------------------------------------------------- helpers
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def clean_text(text):
    """Strip embedded HTML, unescape entities and collapse whitespace."""
    if not text:
        return None
    text = html.unescape(TAG_RE.sub(" ", text))
    text = WS_RE.sub(" ", text).strip()
    return text or None


def txt(elem, path):
    if elem is None:
        return None
    return clean_text(elem.findtext(path))


def enum(value):
    return ENUM_RE.sub("", value) if value else None


def date10(value):
    """'2021-10-19T00:00:00Z' -> '2021-10-19'."""
    if value and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def join(values, sep="; "):
    values = [v for v in dict.fromkeys(values) if v]  # dedupe, keep order
    return sep.join(values) if values else None


def to_json(values):
    return json.dumps(values, ensure_ascii=False) if values else None


# ---------------------------------------------------------------- step 1
def read_bioproject_study_pairs():
    """Stream the experiments TSV and count experiments per (bioproject, sra_study)."""
    log(f"Reading {EXPERIMENTS_TSV}")
    pairs = Counter()
    skipped = 0
    with open(EXPERIMENTS_TSV, encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        i_study, i_bp = header.index("sra_study"), header.index("bioproject")
        for n, line in enumerate(fh, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= max(i_study, i_bp):
                skipped += 1
                continue
            study, bioproject = fields[i_study].strip(), fields[i_bp].strip()
            if not study or not bioproject:
                skipped += 1
                continue
            pairs[(bioproject, study)] += 1
            if n % 5_000_000 == 0:
                log(f"  {n:,} experiments, {len(pairs):,} pairs")
    log(f"Found {len(pairs):,} (bioproject, sra_study) pairs; "
        f"skipped {skipped:,} rows missing bioproject/sra_study")
    return pairs


# ---------------------------------------------------------------- step 2
def parse_publication(pub):
    cit = pub.find("StructuredCitation")
    journal = cit.find("Journal") if cit is not None else None
    authors = []
    if cit is not None:
        for a in cit.iterfind("AuthorSet/Author"):
            name = join([txt(a, "Name/First"), txt(a, "Name/Last")], " ")
            authors.append(name or txt(a, "Consortium"))
    reference = txt(pub, "Reference")
    record = {
        "id": pub.get("id"),
        "db_type": enum(pub.findtext("DbType")),  # Pubmed / DOI / ...
        "status": enum(pub.get("status")),
        "date": date10(pub.get("date")),
        "title": txt(cit, "Title"),
        "journal": txt(journal, "JournalTitle"),
        "year": txt(journal, "Year"),
        "volume": txt(journal, "Volume"),
        "issue": txt(journal, "Issue"),
        "pages": join([txt(journal, "PagesFrom"), txt(journal, "PagesTo")], "-"),
        "authors": [a for a in authors if a],
        # Reference often just repeats the id; keep it only when it's real text
        "reference": reference if reference and reference != pub.get("id") else None,
    }
    return {k: v for k, v in record.items() if v}


def parse_package(pkg, accession):
    proj = pkg.find("Project/Project")
    descr = proj.find("ProjectDescr")
    ptype = proj.find("ProjectType")
    sub = pkg.find("Project/Submission")

    row = {"bioproject_uid": proj.find("ProjectID/ArchiveID").get("id")}

    # --- description
    row["name"] = txt(descr, "Name")
    row["title"] = txt(descr, "Title")
    row["description"] = txt(descr, "Description")
    row["project_release_date"] = date10(descr.findtext("ProjectReleaseDate")) if descr is not None else None

    relevance = descr.find("Relevance") if descr is not None else None
    if relevance is not None:
        row["relevance"] = join(
            [c.tag if (c.text or "").strip().lower() in ("yes", "") else f"{c.tag}: {clean_text(c.text)}"
             for c in relevance])

    centers = [{"center": c.get("center"), "id": clean_text(c.text)}
               for c in proj.iterfind("ProjectID/CenterID")]
    row["center_ids"] = to_json(centers)

    links, geo = [], [c["id"] for c in centers if c["center"] == "GEO"]
    grants, pubs = [], []
    if descr is not None:
        for link in descr.iterfind("ExternalLink"):
            item = {"label": link.get("label") or None, "category": link.get("category")}
            if link.find("URL") is not None:
                item["url"] = txt(link, "URL")
            xref = link.find("dbXREF")
            if xref is not None:
                item["db"] = xref.get("db")
                item["id"] = txt(xref, "ID")
                if item["db"] == "GEO":
                    geo.append(item["id"])
            links.append({k: v for k, v in item.items() if v})
        for g in descr.iterfind("Grant"):
            agency = g.find("Agency")
            item = {"grant_id": g.get("GrantId"), "title": txt(g, "Title"),
                    "agency": clean_text(agency.text) if agency is not None else None,
                    "agency_abbr": agency.get("abbr") if agency is not None else None}
            grants.append({k: v for k, v in item.items() if v})
        pubs = [parse_publication(p) for p in descr.iterfind("Publication")]

    row["external_links"] = to_json(links)
    row["geo_accessions"] = join(geo)
    row["grants"] = to_json(grants)

    # --- publications
    row["publication_count"] = len(pubs)
    row["publications"] = to_json(pubs)
    row["pubmed_ids"] = join([p.get("id") for p in pubs if p.get("db_type", "Pubmed") == "Pubmed"])
    dates = sorted(p["date"] for p in pubs if p.get("date"))
    row["first_publication_date"] = dates[0] if dates else None
    row["journals"] = join([p.get("journal") for p in pubs])
    row["publication_titles"] = join([p.get("title") for p in pubs], " || ")

    # --- project type: organism, target, method, data types
    if ptype is not None:
        org = next(ptype.iter("Organism"), None)
        if org is not None:
            row["organism_name"] = txt(org, "OrganismName")
            row["tax_id"] = org.get("taxID")
            row["supergroup"] = enum(org.findtext("Supergroup"))
        target = next(ptype.iter("Target"), None)
        if target is not None:
            row["target_material"] = enum(target.get("material"))
            row["target_capture"] = enum(target.get("capture"))
            row["sample_scope"] = enum(target.get("sample_scope"))
        method = next(ptype.iter("Method"), None)
        if method is not None:
            row["method_type"] = enum(method.get("method_type"))
        row["objectives"] = join([enum(d.get("data_type")) for d in ptype.iter("Data")])
        row["data_types"] = join([clean_text(d.text) for d in ptype.iter("DataType")])

    # --- submission
    if sub is not None:
        row["submission_id"] = sub.get("submission_id")
        row["submitted_date"] = date10(sub.get("submitted"))
        row["last_update_date"] = date10(sub.get("last_update"))
        org = sub.find("Description/Organization")
        if org is not None:
            row["organization"] = txt(org, "Name")
            row["organization_country"] = txt(org, "Contact/Address/Country")
        row["access"] = txt(sub, "Description/Access")

    # --- umbrella / parent projects
    parents = []
    for link in pkg.iterfind("Project/ProjectLinks/Link"):
        ref = link.find("ProjectIDRef")
        hier = link.find("Hierarchical")
        if ref is not None and hier is not None and ref.get("accession") == accession:
            member = hier.find("MemberID")
            if member is not None and member.get("accession") != accession:
                parents.append(member.get("accession"))
    row["parent_projects"] = join(parents)

    return row


def read_bioproject_xml(wanted):
    """Stream bioproject.xml and parse only the packages whose accession is wanted."""
    log(f"Parsing {BIOPROJECT_XML} for {len(wanted):,} bioprojects")
    info = {}
    context = etree.iterparse(str(BIOPROJECT_XML), events=("end",), tag="Package",
                              huge_tree=True, recover=True)
    for n, (_, pkg) in enumerate(context, 1):
        archive = pkg.find("Project/Project/ProjectID/ArchiveID")
        accession = archive.get("accession") if archive is not None else None
        if accession in wanted:
            try:
                info[accession] = parse_package(pkg, accession)
            except Exception as exc:  # never lose the whole run to one odd record
                log(f"  WARNING: failed to parse {accession}: {exc!r}")
        # free memory
        pkg.clear()
        while pkg.getprevious() is not None:
            del pkg.getparent()[0]
        if n % 100_000 == 0:
            log(f"  {n:,} packages scanned, {len(info):,} matched")
    del context
    log(f"Matched {len(info):,}/{len(wanted):,} bioprojects in the XML")
    return info


# ---------------------------------------------------------------- step 3
def write_outputs(pairs, info):
    log(f"Writing {OUT_CSV}")
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMN_NAMES)
        for (bioproject, study), count in sorted(pairs.items()):
            row = dict(info.get(bioproject, {}))
            row.update(bioproject=bioproject, sra_study=study, n_experiments=count,
                       found_in_bioproject_xml=bioproject in info)
            writer.writerow(["" if row.get(c) is None else row[c] for c in COLUMN_NAMES])

    cols_sql = ",\n".join(f"    {name:<24} {typ}" for name, typ in COLUMNS)
    OUT_SQL.write_text(f"""-- Generated by Automations/create_tables.py
DROP TABLE IF EXISTS {TABLE_NAME};

CREATE TABLE {TABLE_NAME} (
{cols_sql},
    PRIMARY KEY (bioproject, sra_study)
);

\\copy {TABLE_NAME} FROM '{OUT_CSV}' WITH (FORMAT csv, HEADER true)

CREATE INDEX ON {TABLE_NAME} (sra_study);
CREATE INDEX ON {TABLE_NAME} (tax_id);
""", encoding="utf-8")
    log(f"Wrote {len(pairs):,} rows and {OUT_SQL.name}")


def main():
    pairs = read_bioproject_study_pairs()
    wanted = {bp for bp, _ in pairs}
    info = read_bioproject_xml(wanted)
    write_outputs(pairs, info)


if __name__ == "__main__":
    main()
