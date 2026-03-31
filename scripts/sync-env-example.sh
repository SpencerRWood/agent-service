#!/usr/bin/env sh
set -eu

# If there's no real .env, do nothing
[ -f ".env" ] || exit 0

OUT=".env.example"
TMP="$(mktemp)"
NORMALIZED_TMP="$(mktemp)"

# Header
{
  echo "# generated automatically by pre-commit hook (scripts/sync-env-example.sh)"
  echo "# DO NOT PUT SECRETS IN THIS FILE"
  echo
} > "$TMP"

# Transform .env -> .env.example
# - Preserve blank lines and comments
# - For assignments, keep the key and drop the value
# - Normalize whitespace so this hook does not fight pre-commit formatters
awk '
  {
    sub(/[[:space:]]+$/, "", $0)
  }

  /^[[:space:]]*$/ { print ""; next }
  /^[[:space:]]*#/ { print; next }

  /^[[:space:]]*export[[:space:]]+[A-Za-z_][A-Za-z0-9_]*=/ {
    sub(/^[[:space:]]*export[[:space:]]+/, "", $0)
    sub(/[[:space:]]*=.*/, "=", $0)
    print
    next
  }

  /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=/ {
    sub(/^[[:space:]]+/, "", $0)
    sub(/[[:space:]]*=.*/, "=", $0)
    print
    next
  }

  { print }
' .env >> "$TMP"

# Drop trailing blank lines while preserving internal spacing.
awk '
  /^$/ {
    blank_lines++
    next
  }

  {
    while (blank_lines > 0) {
      print ""
      blank_lines--
    }
    print
  }
' "$TMP" > "$NORMALIZED_TMP"

mv "$NORMALIZED_TMP" "$TMP"

# Replace only if changed
if [ ! -f "$OUT" ] || ! cmp -s "$TMP" "$OUT"; then
  mv "$TMP" "$OUT"
else
  rm -f "$TMP"
fi

# Ensure .env is ignored
if [ -f ".gitignore" ]; then
  if ! grep -qxF ".env" .gitignore; then
    printf "\n.env\n" >> .gitignore
  fi
else
  printf ".env\n" > .gitignore
fi

git add "$OUT" .gitignore
