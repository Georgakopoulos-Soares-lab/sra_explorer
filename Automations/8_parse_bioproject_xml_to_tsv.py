#!/usr/bin/env python3

from pathlib import Path
import csv
from lxml import etree


# ============================================================
# SETTINGS
# ============================================================

XML_FILE = "bioproject_data/bioproject_20260528.xml"
OUT_TSV = "all_sra_bioproject_metadata_20260528.tsv"

# Καρφωτές επιλογές progress
PRINT_PROGRESS = True
PROGRESS_EVERY = 100


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def local_name(elem):
    return etree.QName(elem).localname


def first_text(elem, tag_name):
    for x in elem.iter():
        if local_name(x) == tag_name and x.text:
            txt = x.text.strip()
            if txt:
                return txt
    return ""


def all_texts(elem, tag_name):
    values = []

    for x in elem.iter():
        if local_name(x) == tag_name and x.text:
            txt = x.text.strip()
            if txt:
                values.append(txt)

    return "; ".join(sorted(set(values)))


def get_archive_id(elem):
    for x in elem.iter():
        if local_name(x) == "ArchiveID":
            return x.get("accession", ""), x.get("id", "")
    return "", ""


def get_project_type(elem):
    for x in elem.iter():
        if local_name(x) == "ProjectTypeSubmission":
            for child in x:
                return local_name(child)
    return ""


def get_organism(elem):
    organism_name = ""
    taxid = ""

    for x in elem.iter():
        if local_name(x) == "Organism":
            taxid = x.get("taxID", "") or x.get("taxid", "")

            for child in x.iter():
                if local_name(child) == "OrganismName" and child.text:
                    organism_name = child.text.strip()
                    break

            break

    return organism_name, taxid


def get_center_name(elem):
    center_name = first_text(elem, "CenterName")

    if center_name:
        return center_name

    for x in elem.iter():
        if local_name(x) == "Organization":
            for child in x:
                if local_name(child) == "Name" and child.text:
                    name = child.text.strip()
                    abbr = child.get("abbr", "")

                    if abbr and abbr != name:
                        return f"{name} ({abbr})"

                    return name

    return ""


def get_biosample_ids(elem):
    values = []

    for x in elem.iter():
        biosample_id = x.get("biosample_id")
        if biosample_id:
            values.append(biosample_id)

        biosample = x.get("biosample")
        if biosample:
            values.append(biosample)

        accession = x.get("accession")
        if accession and accession.startswith("SAM"):
            values.append(accession)

        if local_name(x) in {"BioSample", "BioSampleId", "BioSampleID"} and x.text:
            txt = x.text.strip()
            if txt:
                values.append(txt)

    return "; ".join(sorted(set(values)))


def get_publication_ids(elem):
    values = []

    for x in elem.iter():
        if local_name(x) == "Publication":
            pub_id = x.get("id", "")
            if pub_id:
                values.append(pub_id)

    return "; ".join(sorted(set(values)))


def get_publication_titles(elem):
    values = []

    for x in elem.iter():
        if local_name(x) == "Publication":
            for child in x.iter():
                if local_name(child) == "Title" and child.text:
                    txt = child.text.strip()
                    if txt:
                        values.append(txt)

    return " || ".join(sorted(set(values)))


def get_external_links(elem):
    values = []

    for x in elem.iter():
        if local_name(x) == "URL" and x.text:
            txt = x.text.strip()
            if txt:
                values.append(txt)

    return "; ".join(sorted(set(values)))


def get_locus_tag_prefixes(elem):
    values = []

    for x in elem.iter():
        if local_name(x) == "LocusTagPrefix":
            prefix = x.text.strip() if x.text else ""
            biosample_id = x.get("biosample_id", "")
            assembly_id = x.get("assembly_id", "")

            parts = []

            if prefix:
                parts.append(prefix)

            if biosample_id:
                parts.append(f"biosample_id={biosample_id}")

            if assembly_id:
                parts.append(f"assembly_id={assembly_id}")

            if parts:
                values.append("|".join(parts))

    return "; ".join(sorted(set(values)))


def get_linked_projects(elem):
    values = []

    for x in elem.iter():
        if local_name(x) in {"ProjectIDRef", "MemberID"}:
            accession = x.get("accession", "")
            if accession:
                values.append(accession)

    return "; ".join(sorted(set(values)))


def get_data_types(elem):
    values = []

    for x in elem.iter():
        if local_name(x) == "DataType" and x.text:
            txt = x.text.strip()
            if txt:
                values.append(txt)

    return "; ".join(sorted(set(values)))


def get_target_attributes(elem):
    capture = ""
    material = ""
    sample_scope = ""

    for x in elem.iter():
        if local_name(x) == "Target":
            capture = x.get("capture", "")
            material = x.get("material", "")
            sample_scope = x.get("sample_scope", "")
            break

    return capture, material, sample_scope


def get_method_type(elem):
    for x in elem.iter():
        if local_name(x) == "Method":
            return x.get("method_type", "")
    return ""


def get_genome_size(elem):
    for x in elem.iter():
        if local_name(x) == "GenomeSize":
            value = x.text.strip() if x.text else ""
            units = x.get("units", "")
            return value, units

    return "", ""


def get_submission_date(elem):
    for x in elem.iter():
        if local_name(x) == "Submission":
            return x.get("submitted", "")
    return ""


def get_access(elem):
    return first_text(elem, "Access")


# ============================================================
# OUTPUT COLUMNS
# ============================================================

columns = [
    "bioproject_accession",
    "bioproject_id",

    "name",
    "title",
    "description",

    "project_type",
    "data_types",
    "method_type",

    "organism_name",
    "taxid",
    "strain",
    "supergroup",
    "disease",

    "genome_size",
    "genome_size_units",

    "target_capture",
    "target_material",
    "sample_scope",

    "center_name",
    "access",
    "submitted",
    "project_release_date",

    "biosample_accessions",
    "locus_tag_prefixes",

    "publication_ids",
    "publication_titles",

    "external_links",
    "linked_projects",
]


# ============================================================
# MAIN
# ============================================================

Path(OUT_TSV).parent.mkdir(parents=True, exist_ok=True)

if PRINT_PROGRESS:
    print("Streaming BioProject XML...")
    print(f"Input:  {XML_FILE}")
    print(f"Output: {OUT_TSV}")
    print(f"Progress every: {PROGRESS_EVERY:,} records")

count = 0

with open(OUT_TSV, "w", newline="", encoding="utf-8") as out:
    writer = csv.DictWriter(
        out,
        fieldnames=columns,
        delimiter="\t",
        extrasaction="ignore"
    )

    writer.writeheader()

    context = etree.iterparse(
        XML_FILE,
        events=("end",),
        huge_tree=True,
        recover=True,
    )

    for event, elem in context:
        if local_name(elem) != "Package":
            continue

        accession, archive_id = get_archive_id(elem)
        organism_name, taxid = get_organism(elem)
        genome_size, genome_size_units = get_genome_size(elem)
        target_capture, target_material, sample_scope = get_target_attributes(elem)

        row = {
            "bioproject_accession": accession,
            "bioproject_id": archive_id,

            "name": first_text(elem, "Name"),
            "title": first_text(elem, "Title"),
            "description": first_text(elem, "Description"),

            "project_type": get_project_type(elem),
            "data_types": get_data_types(elem),
            "method_type": get_method_type(elem),

            "organism_name": organism_name,
            "taxid": taxid,
            "strain": first_text(elem, "Strain"),
            "supergroup": first_text(elem, "Supergroup"),
            "disease": first_text(elem, "Disease"),

            "genome_size": genome_size,
            "genome_size_units": genome_size_units,

            "target_capture": target_capture,
            "target_material": target_material,
            "sample_scope": sample_scope,

            "center_name": get_center_name(elem),
            "access": get_access(elem),
            "submitted": get_submission_date(elem),
            "project_release_date": first_text(elem, "ProjectReleaseDate"),

            "biosample_accessions": get_biosample_ids(elem),
            "locus_tag_prefixes": get_locus_tag_prefixes(elem),

            "publication_ids": get_publication_ids(elem),
            "publication_titles": get_publication_titles(elem),

            "external_links": get_external_links(elem),
            "linked_projects": get_linked_projects(elem),
        }

        writer.writerow(row)
        count += 1

        if PRINT_PROGRESS and count % PROGRESS_EVERY == 0:
            print(f"Processed {count:,} BioProjects")

        # Καθαρισμός μνήμης
        elem.clear()

        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]


if PRINT_PROGRESS:
    print("Done.")
    print(f"Exported BioProjects: {count:,}")
    print(f"TSV file: {OUT_TSV}")