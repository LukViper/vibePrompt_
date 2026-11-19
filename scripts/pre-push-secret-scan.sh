#!/usr/bin/env bash
# Reject pushes that would publish likely secrets in the commits being pushed.
set -euo pipefail

# Built in pieces so this file itself does not match the scanner.
P1='sk-'"[A-Za-z0-9_-]{10,}"
P2='pk_'"live_[A-Za-z0-9]+"
P3='AKIA'"[0-9A-Z]{16}"
P4='BEGIN (RSA |OPENSSH )?PRIVATE KEY'
PATTERN="${P1}|${P2}|${P3}|${P4}"

z40=0000000000000000000000000000000000000000
found=0

while read -r local_ref local_sha remote_ref remote_sha; do
  if [[ "$local_sha" == "$z40" ]]; then
    continue
  fi
  if [[ "$remote_sha" == "$z40" ]]; then
    range="$local_sha"
  else
    range="${remote_sha}..${local_sha}"
  fi
  if git diff --name-only "$range" 2>/dev/null | grep -qE '(^|/)\.env$|\.pem$|credentials\.json$'; then
    echo "pre-push: refusing to push secret-looking paths in $range" >&2
    git diff --name-only "$range" | grep -E '(^|/)\.env$|\.pem$|credentials\.json$' >&2 || true
    found=1
  fi
  matches="$(
    git grep -nE "$PATTERN" "$local_sha" -- \
      ':!*.example' ':!*.md' ':!docs/**' ':!*.test.*' \
      ':!**/fixtures/**' ':!scripts/pre-push-secret-scan.sh' \
      2>/dev/null | head -40 || true
  )"
  if [[ -n "$matches" ]]; then
    echo "$matches" >&2
    echo "pre-push: potential secret pattern matched in $local_sha" >&2
    found=1
  fi
done

if [[ "$found" -ne 0 ]]; then
  echo "pre-push: blocked. Remove secrets and try again." >&2
  exit 1
fi
exit 0
