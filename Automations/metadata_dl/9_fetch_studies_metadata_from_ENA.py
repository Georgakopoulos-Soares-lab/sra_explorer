from pathlib import Path
import time
import requests
import pandas as pd


# ============================================================
# Settings
# ============================================================

INPUT_FILE = "all_sra_studies.txt"

OUT_DIR = Path("ena_study_metadata_by_id")
FAILED_DIR = Path("ena_study_metadata_failed")

FINAL_OUTPUT = "ena_study_metadata_all.tsv"

BASE_URL = "https://www.ebi.ac.uk/ena/portal/api/search"

SLEEP_SECONDS = 0.05
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3

OUT_DIR.mkdir(exist_ok=True)
FAILED_DIR.mkdir(exist_ok=True)

# ============================================================
# Fields to retrieve from ENA read_run
# ============================================================

FIELDS = [
    "run_accession",
    "study_accession",
    "secondary_study_accession",
    "study_title",
    "study_alias",
    "description",
    "center_name",
    "first_public",
    "last_updated",
]


# ============================================================
# Read study IDs
# ============================================================

studies = [
    line.strip()
    for line in Path(INPUT_FILE).read_text().splitlines()
    if line.strip()
]

# remove duplicates while preserving order
studies = list(dict.fromkeys(studies))

print(f"Total unique studies: {len(studies)}")


# ============================================================
# Helper: choose correct ENA query field
# ============================================================

def get_query_field(study_id: str) -> str:
    """
    SRP/DRP/PRJ accessions are usually secondary accessions in ENA.
    ERP accessions are usually primary ENA study accessions.
    """
    if study_id.startswith(("SRP", "DRP", "PRJ")):
        return "secondary_study_accession"
    else:
        return "study_accession"


# ============================================================
# Fetch metadata per study
# ============================================================

for i, study in enumerate(studies[0:10], start=1):

    out_file = OUT_DIR / f"{study}.tsv"
    failed_file = FAILED_DIR / f"{study}.failed.txt"

    # resume support
    if out_file.exists() and out_file.stat().st_size > 0:
        continue

    query_field = get_query_field(study)

    params = {
        "result": "read_run",
        "query": f'{query_field}="{study}"',
        "fields": ",".join(FIELDS),
        "format": "tsv",
        "limit": "1",
    }

    success = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BASE_URL, params=params, timeout=TIMEOUT_SECONDS)
            r.raise_for_status()

            text = r.text.strip()

            # Write response even if it contains only header.
            # This prevents endless retries for studies not found in ENA.
            out_file.write_text(r.text)

            success = True
            break

        except Exception as e:
            if attempt == MAX_RETRIES:
                failed_file.write_text(
                    f"study={study}\n"
                    f"query_field={query_field}\n"
                    f"error={repr(e)}\n"
                )
            else:
                time.sleep(1)

    if i % 1000 == 0:
        print(f"Processed {i}/{len(studies)}")

    time.sleep(SLEEP_SECONDS)


# ============================================================
# Merge all results
# ============================================================

print("Merging results...")

dfs = []

for f in sorted(OUT_DIR.glob("*.tsv")):
    try:
        df = pd.read_csv(f, sep="\t", dtype=str)

        # skip files with only header and no data rows
        if len(df) == 0:
            continue

        # keep original requested study id from filename
        df["requested_study"] = f.stem

        dfs.append(df)

    except Exception:
        pass

if not dfs:
    raise SystemExit("No metadata retrieved.")

merged = pd.concat(dfs, ignore_index=True)

# one row per requested study
merged = merged.drop_duplicates(subset=["requested_study"])

# Reorder useful columns
preferred_cols = [
    "requested_study",
    "study_accession",
    "secondary_study_accession",
    "study_title",
    "study_alias",
    "description",
    "center_name",
    "first_public",
    "last_updated",
    "run_accession",
]

cols = [c for c in preferred_cols if c in merged.columns] + [
    c for c in merged.columns if c not in preferred_cols
]

merged = merged[cols]

merged.to_csv(FINAL_OUTPUT, sep="\t", index=False)

print(f"Written: {FINAL_OUTPUT}")
print(f"Rows with metadata: {len(merged)}")
print(f"Failed requests: {len(list(FAILED_DIR.glob('*.failed.txt')))}")