# Auto_update: the weekly database update

`update.py` fetches the new SRA runs and BioProject metadata, loads them into the database (inserts and updates only, never deletes), builds the embeddings and tags of the new projects and refreshes the views. A systemd timer runs it every Sunday at 02:00.

Everything about it (steps, options, the timer, resuming a failed run, tunables, troubleshooting) is in [docs/auto-update.md](../../docs/auto-update.md).

Setup on a new machine: `bash install.sh`. Run by hand: `.venv/bin/python update.py --list` / `--dry-run` / `--from STEP`.
