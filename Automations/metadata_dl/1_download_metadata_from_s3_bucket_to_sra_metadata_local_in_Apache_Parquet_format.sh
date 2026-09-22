#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# Download all public NCBI SRA metadata from AWS S3
# Source:
#   s3://sra-pub-metadata-us-east-1/sra/metadata/
#
# This downloads METADATA only, not all .sra/.fastq files.
# ============================================================

REMOTE="s3://sra-pub-metadata-us-east-1/sra/metadata/"
LOCAL_DIR="sra_metadata_local"
LOG_DIR="logs"

mkdir -p "$LOCAL_DIR" "$LOG_DIR"

echo "============================================"
echo "NCBI SRA metadata local mirror"
echo "Remote: $REMOTE"
echo "Local:  $LOCAL_DIR"
echo "============================================"

echo
echo "[1/4] Checking AWS CLI..."
if ! command -v aws >/dev/null 2>&1; then
    echo "ERROR: aws CLI not found."
    echo "Install with:"
    echo "  sudo apt install awscli"
    echo "or:"
    echo "  conda install -c conda-forge awscli"
    exit 1
fi

aws --version

echo
echo "[2/4] Listing remote files..."
aws s3 ls "$REMOTE" \
    --recursive \
    --no-sign-request \
    > "$LOG_DIR/sra_metadata_filelist.txt"

FILE_COUNT=$(wc -l < "$LOG_DIR/sra_metadata_filelist.txt")

TOTAL_BYTES=$(awk '{sum += $3} END {print sum}' "$LOG_DIR/sra_metadata_filelist.txt")

TOTAL_GB=$(awk -v bytes="$TOTAL_BYTES" 'BEGIN {printf "%.2f", bytes/1024/1024/1024}')

echo "Remote files: $FILE_COUNT"
echo "Total size:   $TOTAL_GB GB"

echo
echo "[3/4] Dry-run first..."
aws s3 sync "$REMOTE" "$LOCAL_DIR" \
    --no-sign-request \
    --dryrun \
    > "$LOG_DIR/sra_metadata_dryrun.txt"

echo "Dry-run written to:"
echo "  $LOG_DIR/sra_metadata_dryrun.txt"

echo
echo "[4/4] Starting real download..."
echo "This is resumable. If it stops, run the same script again."

aws s3 sync "$REMOTE" "$LOCAL_DIR" \
    --no-sign-request \
    --only-show-errors \
    > "$LOG_DIR/sra_metadata_download.log" 2>&1

echo
echo "Download finished."

echo
echo "Verifying local files..."
LOCAL_COUNT=$(find "$LOCAL_DIR" -type f | wc -l)

echo "Remote file count: $FILE_COUNT"
echo "Local file count:  $LOCAL_COUNT"

echo
echo "Done."
echo "Metadata saved in:"
echo "  $LOCAL_DIR"