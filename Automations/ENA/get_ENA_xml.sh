#!/usr/bin/env bash
# Download NCBI's BioProject dump (bioproject.xml, ~4 GB, refreshed daily) into
# this folder. The weekly update pipeline (Automations/Auto_update) runs it,
# and it can be run by hand: bash Automations/ENA/get_ENA_xml.sh
#
# -N (timestamping) compares the server's Last-Modified with the local file,
# so an unchanged file is not downloaded again. --continue resumes a partial
# file of the same dump; --tries retries a dropped connection within this run.
set -euo pipefail
cd "$(dirname "$0")"

URL="https://ftp.ncbi.nlm.nih.gov/bioproject/bioproject.xml"
FILE="bioproject.xml"

# A leftover of an interrupted download must not be resumed once NCBI has
# published a newer dump: the halves would come from two different files.
# A complete file ends with the root's closing tag (download.py checks the same).
if [ -f "$FILE" ] && [ "$(find "$FILE" -mmin +720)" ] && ! tail -c 256 "$FILE" | grep -q "</PackageSet>"; then
    echo "removing a partial $FILE older than 12 hours (resuming it could mix two dumps)"
    rm -f "$FILE"
fi

wget -N --tries=5 --waitretry=30 --continue --progress=dot:giga "$URL"

if ! tail -c 256 "$FILE" | grep -q "</PackageSet>"; then
    echo "ERROR: $FILE is incomplete (no </PackageSet> at the end)" >&2
    exit 1
fi
ls -l "$FILE"
