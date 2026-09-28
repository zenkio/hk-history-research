#!/usr/bin/env bash
# Save a pipeline log to the `logs` branch of the repository in the current folder (the private
# data repository). The branch holds one commit with the last KEEP_DAYS days of logs and is
# replaced each time, so logs never pile up in the history. Usage: save_log.sh <log file>
set -euo pipefail
LOG="${1:?usage: save_log.sh <log file>}"
KEEP_DAYS="${KEEP_DAYS:-7}"
[ -f "$LOG" ] || { echo "no log to save"; exit 0; }

DIR="$(mktemp -d)"
if git fetch -q origin logs 2>/dev/null; then
  git archive FETCH_HEAD | tar -x -C "$DIR"
fi
cp "$LOG" "$DIR/"
# Log names start with their date (YYYY-MM-DD-...); drop the ones older than KEEP_DAYS.
CUTOFF="$(date -u -d "-$KEEP_DAYS days" +%Y-%m-%d)"
for f in "$DIR"/*.log; do
  [ "$(basename "$f" | cut -c1-10)" \< "$CUTOFF" ] && rm -f "$f"
done

# Build the single commit in a separate index so the working tree and main are untouched.
# (The index lives outside the folder, or git would commit its lock file with the logs.)
export GIT_INDEX_FILE="$(mktemp -u)"
git --work-tree="$DIR" add -A -- .
TREE="$(git write-tree)"
COMMIT="$(echo "pipeline logs, last $KEEP_DAYS days" | git commit-tree "$TREE")"
rm -f "$GIT_INDEX_FILE"; unset GIT_INDEX_FILE
git push -q -f origin "$COMMIT:refs/heads/logs"
echo "log saved to the logs branch ($(ls "$DIR"/*.log | wc -l) files)"
