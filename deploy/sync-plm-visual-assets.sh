#!/bin/sh
# Apply packaged prompt assets to existing durable workflow state only.
# Credentials, model configuration, other skills and conversations are untouched.
set -eu

payload=/opt/plm-visual-update
hermes_home=/home/hermes/.hermes
workflow_source=/opt/plm-workflow-target

test -s "$payload/SOUL.md"
test -s "$payload/plm-quick-SKILL.md"
test -d "$hermes_home"
test -d "$workflow_source/skills/plm/plm-quick"

sync_profile() {
    target=$1
    test -f "$target/SOUL.md"
    test -d "$target/skills/workspace-skills/plm/plm-quick"
    cp "$payload/SOUL.md" "$target/SOUL.md"
    cp "$payload/plm-quick-SKILL.md" "$target/skills/workspace-skills/plm/plm-quick/SKILL.md"
}

# Keep the existing workflow initializer's source in sync so a later restart
# cannot restore the previous prompt assets.
cp "$payload/SOUL.md" "$workflow_source/SOUL.md"
cp "$payload/plm-quick-SKILL.md" "$workflow_source/skills/plm/plm-quick/SKILL.md"
sync_profile "$hermes_home"
for profile in "$hermes_home"/profiles/*; do
    [ -d "$profile" ] || continue
    # Only existing PLM profiles participate in this update.
    [ -f "$profile/SOUL.md" ] || continue
    [ -d "$profile/skills/workspace-skills/plm/plm-quick" ] || continue
    sync_profile "$profile"
done

printf 'PLM visual prompt assets synchronized.\n'
