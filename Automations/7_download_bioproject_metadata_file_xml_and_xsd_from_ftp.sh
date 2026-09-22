#!/usr/bin/env bash

# Download BioProject XML dump
# This file is updated daily by NCBI

URL="https://ftp.ncbi.nlm.nih.gov/bioproject/bioproject.xml"
OUT_DIR="bioproject_data"
DATE_TAG=$(date +"%Y%m%d")

mkdir -p "$OUT_DIR"

OUT_FILE="${OUT_DIR}/bioproject_${DATE_TAG}.xml"

wget -O "$OUT_FILE" "$URL"

echo "Downloaded:"
echo "$OUT_FILE"


#############################################################################
# Download BioProject XSD schema

URL="https://ftp.ncbi.nlm.nih.gov/bioproject/Schema.v.1.2/core_bioproject.xsd"
OUT_DIR="bioproject_data"

mkdir -p "$OUT_DIR"

OUT_FILE="${OUT_DIR}/core_bioproject.xsd"

wget -O "$OUT_FILE" "$URL"

echo "Downloaded:"
echo "$OUT_FILE"