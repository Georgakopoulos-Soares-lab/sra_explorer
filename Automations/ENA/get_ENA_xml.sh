#!/usr/bin/env bash
# Download NCBI's BioProject dump (bioproject.xml, ~4 GB, rewritten daily) into
# this folder. The weekly update pipeline (Automations/Auto_update) runs it,
# and it can be run by hand: bash Automations/ENA/get_ENA_xml.sh
#
# -N (timestamping) compares the server's Last-Modified with the local file,
# so an unchanged file is not downloaded again; --tries retries a dropped
# connection within this run. A partial file is never resumed: NCBI rewrites
# the dump every day, so the halves could come from two different dumps and
# the result would still end with the closing tag. An incomplete file is
# deleted first and the dump fetched whole again.
set -euo pipefail
cd "$(dirname "$0")"

URL="https://ftp.ncbi.nlm.nih.gov/bioproject/bioproject.xml"
FILE="bioproject.xml"

complete() { [ -f "$FILE" ] && tail -c 256 "$FILE" | grep -q "</PackageSet>"; }

if [ -f "$FILE" ] && ! complete; then
    echo "removing incomplete $FILE (it will be downloaded again whole)"
    rm -f "$FILE"
fi

wget -N --tries=5 --waitretry=30 --progress=dot:giga "$URL"

if ! complete; then
    echo "ERROR: $FILE is incomplete (no </PackageSet> at the end)" >&2
    exit 1
fi
ls -l "$FILE"
