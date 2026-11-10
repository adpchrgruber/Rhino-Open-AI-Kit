#!/bin/bash
# Scan the kit for personal traces before publishing: home paths, user/host names, e-mail
# addresses, machine names. Usage: tools/privacy-check.sh [extra words to look for ...]
# Exit code 1 if anything is found. Run it from anywhere.
cd "$(dirname "$0")/.." || exit 2
words=("/Users/" "/home/" "C:\\\\Users" "@gmail" "@icloud" "@outlook" "MacBook" "$(whoami)" "$(hostname -s 2>/dev/null)" "$@")
found=0
for w in "${words[@]}"; do
  [ -z "$w" ] && continue
  hits="$(grep -rIn --exclude-dir=.git --exclude=privacy-check.sh -F -- "$w" . 2>/dev/null)"
  if [ -n "$hits" ]; then echo "== '$w'"; echo "$hits"; found=1; fi
done
# any e-mail address
hits="$(grep -rInE --exclude-dir=.git --exclude=privacy-check.sh '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}' . )"
[ -n "$hits" ] && { echo "== e-mail addresses"; echo "$hits"; found=1; }
# files that must not be published
big="$(find . -path ./.git -prune -o -type f \( -name '*.gguf' -o -name 'llama-server*' -o -size +2M \) -print)"
[ -n "$big" ] && { echo "== binaries or large files"; echo "$big"; found=1; }
[ "$found" = 0 ] && echo "Clean: no personal traces found."
exit $found
