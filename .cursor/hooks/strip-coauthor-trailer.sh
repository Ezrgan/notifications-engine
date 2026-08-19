#!/usr/bin/env bash
# Remove Cursor-injected Co-authored-by trailers from git commit shell commands.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("command",""))')

if [[ "$command" != *"git commit"* ]]; then
  printf '%s\n' '{}'
  exit 0
fi

cleaned=$(
  printf '%s' "$command" | python3 -c '
import re, sys
cmd = sys.stdin.read()
cmd = re.sub(
    r'\'' --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>"'\'',
    "",
    cmd,
)
cmd = re.sub(
    r'\'' --trailer='\''Co-authored-by: Cursor <cursoragent@cursor.com>'\'''\''',
    "",
    cmd,
)
print(cmd, end="")
'
)

if [[ "$cleaned" == "$command" ]]; then
  printf '%s\n' '{}'
  exit 0
fi

python3 -c 'import json,sys; print(json.dumps({"updated_input": {"command": sys.argv[1]}}))' "$cleaned"
