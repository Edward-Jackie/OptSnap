#!/bin/bash
# OptSnap launcher — run from anywhere with uv installed.
# Save this script somewhere in your PATH (e.g., /usr/local/bin/optsnap)
# or add an alias to your shell config.

cd /Users/jack/dev/my/OptSnap && uv run python -m optsnap "$@"
