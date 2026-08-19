#!/usr/bin/env bash
# Commit staged or listed paths using a message file — avoids Shell auto-injecting
# Co-authored-by trailers on bare `git commit -m` invocations.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: git-commit.sh <message-file> <path>..." >&2
  exit 1
fi

msg_file=$1
shift

if [[ ! -f "$msg_file" ]]; then
  echo "message file not found: $msg_file" >&2
  exit 1
fi

git add "$@"
/usr/bin/git commit -F "$msg_file"

if /usr/bin/git log -1 --format=%B | grep -qi 'co-authored-by'; then
  echo "error: commit message contains a Co-authored-by trailer" >&2
  exit 1
fi
