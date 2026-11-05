#!/usr/bin/env bash
# Download NCBI's BioProject dump (bioproject.xml, ~4 GB, rewritten daily) into
# this folder. The weekly update pipeline (Automations/Auto_update) runs it,
# and it can be run by hand: bash Automations/ENA/get_ENA_xml.sh
#
# The server's Last-Modified is compared with the local file first, so an
# unchanged dump is not downloaded again. A new dump is fetched whole into
# bioproject.xml.new and only moved over bioproject.xml once it is complete,
# so a failed transfer leaves the previous complete file in place. A partial
# file is never resumed: NCBI rewrites the dump every day, and resuming could
# join the halves of two different dumps into a file that still looks
# complete. wget's --tries retries a dropped connection within this run.
set -euo pipefail
cd "$(dirname "$0")"

URL="https://ftp.ncbi.nlm.nih.gov/bioproject/bioproject.xml"
FILE="bioproject.xml"
NEW="$FILE.new"

complete() { [ -f "$1" ] && tail -c 256 "$1" | grep -q "</PackageSet>"; }

rm -f "$NEW"                                # a partial download from an interrupted run
if [ -f "$FILE" ] && ! complete "$FILE"; then
    echo "removing incomplete $FILE"
    rm -f "$FILE"
fi

# Skip the download when the local complete file is as new as the server's.
remote_lm="$(curl -sIL --max-time 60 "$URL" | awk -F': ' 'tolower($1) == "last-modified" {print $2}' | tr -d '\r' | tail -n 1)"
if [ -f "$FILE" ] && [ -n "$remote_lm" ] && [ "$(date -d "$remote_lm" +%s)" -le "$(stat -c %Y "$FILE")" ]; then
    echo "$FILE is up to date (server: $remote_lm)"
    ls -l "$FILE"
    exit 0
fi

echo "downloading $URL (server: ${remote_lm:-unknown date})"
wget --tries=5 --waitretry=30 --progress=dot:giga -O "$NEW" "$URL"

if ! complete "$NEW"; then
    echo "ERROR: $NEW is incomplete (no </PackageSet> at the end)" >&2
    rm -f "$NEW"
    exit 1
fi
[ -n "$remote_lm" ] && touch -d "$remote_lm" "$NEW"
mv -f "$NEW" "$FILE"
ls -l "$FILE"
