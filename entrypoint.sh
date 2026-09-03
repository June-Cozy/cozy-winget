#!/usr/bin/env sh
set -eu

REPO_URL="${MANIFEST_REPO_URL:-https://github.com/June-Cozy/cozy-winget.git}"
REPO_DIR="${MANIFEST_REPO_DIR:-/data/cozy-winget}"
PULL_INTERVAL="${MANIFEST_PULL_INTERVAL:-86400}"

if [ ! -d "$REPO_DIR/.git" ]; then
    git clone "$REPO_URL" "$REPO_DIR"
    git -C "$REPO_DIR" lfs pull
else
    git -C "$REPO_DIR" pull --ff-only
    git -C "$REPO_DIR" lfs pull
fi

(
    while true; do
        sleep "$PULL_INTERVAL"
        echo "[entrypoint] pulling $REPO_URL"
        if git -C "$REPO_DIR" pull --ff-only; then
            git -C "$REPO_DIR" lfs pull
        else
            echo "[entrypoint] pull failed, keeping stale manifest"
        fi
    done
) &

exec python3 serve_manifest.py "$REPO_DIR/manifest.jsonl" --watch --port 8080
