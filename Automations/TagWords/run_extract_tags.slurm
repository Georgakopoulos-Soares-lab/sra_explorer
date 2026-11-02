#!/bin/bash
# Tag new bioprojects (incremental: projects already in output/bioproject_tags.tsv are skipped).
# Run after create_tables.py and create_embeddings.py:  sbatch run_extract_tags.slurm
#SBATCH -J bioproject_tags
#SBATCH -p normal
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 06:00:00
#SBATCH -o extract_tags.%j.log
##SBATCH -A <allocation>

cd /work/11795/dgrigor/ls6/projects/sra_explorer/Automations/TagWords || exit 1
unset OMP_NUM_THREADS
# ~3 GB RAM per worker (worker count is capped by free RAM); 2 threads per worker was fastest.
python3 extract_tags.py --threads-per-worker 2 "$@"
