#!/usr/bin/env bash
# Sets up the weekly update pipeline on this machine (docs/auto-update.md):
# the three virtual environments it needs, the systemd service and timer.
# Safe to run again: existing venvs are left alone, unit files are replaced.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # Automations/Auto_update
AUTOMATIONS="$(dirname "$HERE")"
ROOT="$(dirname "$AUTOMATIONS")"
PYTHON="${PYTHON:-python3}"                              # 3.14 on the production host
TORCH_INDEX="https://download.pytorch.org/whl/cpu"       # no GPU here: the CPU build avoids CUDA downloads

say() { printf '\n== %s\n' "$*"; }

# make_venv DIR : creates DIR/.venv with pip up to date when it does not exist yet.
# Returns 1 when it already existed (so the caller skips the package installs).
make_venv() {
    local dir="$1"
    if [ -x "$dir/.venv/bin/python" ]; then
        echo "$dir/.venv exists: keeping it (delete it to rebuild)"
        return 1
    fi
    "$PYTHON" -m venv "$dir/.venv"
    "$dir/.venv/bin/pip" install --quiet --upgrade pip
}

say "pipeline venv: $HERE/.venv"
[ -f "$HERE/requirements.txt" ] || { echo "missing $HERE/requirements.txt" >&2; exit 1; }
if make_venv "$HERE"; then
    "$HERE/.venv/bin/pip" install -r "$HERE/requirements.txt"
fi

say "backend venv (create_embeddings.py, normalize apply): $ROOT/backend/.venv"
if make_venv "$ROOT/backend"; then
    # torch first, from the CPU index, as docs/production.md says.
    "$ROOT/backend/.venv/bin/pip" install torch --index-url "$TORCH_INDEX"
    "$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
fi

say "TagWords venv (extract_tags.py): $AUTOMATIONS/TagWords/.venv"
if make_venv "$AUTOMATIONS/TagWords"; then
    "$AUTOMATIONS/TagWords/.venv/bin/pip" install torch --index-url "$TORCH_INDEX"
    "$AUTOMATIONS/TagWords/.venv/bin/pip" install gliner sentence-transformers numpy
fi

say "folders and smoke test"
mkdir -p "$HERE/data/sra_metadata" "$HERE/data/output" "$HERE/work" "$HERE/state" "$HERE/logs"
"$HERE/.venv/bin/python" "$HERE/update.py" --list

say "systemd units"
if ! command -v systemctl >/dev/null; then
    echo "systemctl not found: units not installed (run update.py from cron or by hand)"; exit 0
fi
install -m 644 "$HERE/systemd/srascout-update.service" /etc/systemd/system/srascout-update.service
install -m 644 "$HERE/systemd/srascout-update.timer" /etc/systemd/system/srascout-update.timer
systemctl daemon-reload
systemctl enable --now srascout-update.timer
systemctl list-timers srascout-update.timer --no-pager

cat <<MSG

Installed. The update runs every Sunday at 02:00.
  status:    systemctl status srascout-update.service
  logs:      journalctl -u srascout-update -f     (also $HERE/logs/)
  run now:   systemctl start srascout-update.service
  dry run:   cd $HERE && .venv/bin/python update.py --dry-run
MSG
