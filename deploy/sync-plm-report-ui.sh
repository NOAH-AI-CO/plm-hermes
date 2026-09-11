#!/bin/sh
# Mount the existing extension directory at /target. Publish the manifest last
# so clients only request the new version once the new script is in place.
set -eu
payload=/opt/plm-report-ui
target=/target
test -d "$target"
for file in noah-plm-panels.js manifest.json; do
    test -s "$payload/$file"
    test -f "$target/$file"
    test ! -L "$target/$file"
done
temporary=
trap '[ -z "$temporary" ] || rm -f "$temporary"' EXIT HUP INT TERM
for file in noah-plm-panels.js manifest.json; do
    temporary=$(mktemp "$target/.plm-report-ui.XXXXXX")
    cp -p "$target/$file" "$temporary"
    cat "$payload/$file" > "$temporary"
    mv -f "$temporary" "$target/$file"
    temporary=
done
printf 'PLM report UI assets published.\n'
