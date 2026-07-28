#!/usr/bin/env bash
set -euo pipefail

readonly app_dir=/home/azureuser/plm-hermes
readonly compose_dir="$app_dir/deploy"

usage() {
    printf 'Usage: %s <commit> <release-id>\n' "${0##*/}" >&2
    exit 2
}

[[ ${EUID} -eq 0 && $# -eq 2 ]] || usage
commit=$1
release_id=$2

[[ $commit =~ ^[0-9a-f]{40}$ ]] || {
    printf 'Commit must be a lowercase 40-character Git commit.\n' >&2
    exit 2
}
[[ $release_id =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$ ]] || {
    printf 'Release ID contains unsupported characters.\n' >&2
    exit 2
}
[[ -d $app_dir/.git && -f $compose_dir/docker-compose.yml && -f $app_dir/webui/Dockerfile.client ]] || {
    printf 'PLM deployment is not provisioned.\n' >&2
    exit 1
}
[[ -z $(git -C "$app_dir" status --porcelain) ]] || {
    printf 'Production checkout has uncommitted tracked changes.\n' >&2
    exit 1
}

git -C "$app_dir" fetch --quiet origin yiyong-prod
git -C "$app_dir" merge-base --is-ancestor "$commit" origin/yiyong-prod || {
    printf 'Commit is not reachable from origin/yiyong-prod.\n' >&2
    exit 1
}
git -C "$app_dir" checkout --quiet --force yiyong-prod
git -C "$app_dir" reset --quiet --hard "$commit"
[[ $(git -C "$app_dir" rev-parse HEAD) == "$commit" ]] || {
    printf 'Checked-out revision does not match the approved commit.\n' >&2
    exit 1
}

docker build \
    --label "org.opencontainers.image.revision=$commit" \
    --label 'io.yiyong.deployment-target=biz' \
    --tag "plm-hermes-webui:$commit" \
    --tag plm-hermes-webui:latest \
    --file "$app_dir/webui/Dockerfile.client" \
    "$app_dir/webui"

mkdir -p "$compose_dir/hermes-home/webui/extensions"
rsync -a --delete "$app_dir/hermes-config/webui-extensions/noah/" "$compose_dir/hermes-home/webui/extensions/noah/"
cp "$app_dir/hermes-config/SOUL.md" "$compose_dir/hermes-home/SOUL.md"
[[ -f $app_dir/hermes-config/config.yaml ]] && cp "$app_dir/hermes-config/config.yaml" "$compose_dir/hermes-home/config.yaml"

if [[ -d $app_dir/skills/plm ]]; then
    mkdir -p "$compose_dir/hermes-home/skills/workspace-skills/plm"
    rsync -a --delete "$app_dir/skills/plm/" "$compose_dir/hermes-home/skills/workspace-skills/plm/"
    for profile in "$compose_dir"/hermes-home/profiles/*; do
        [[ -d $profile ]] || continue
        cp "$app_dir/hermes-config/SOUL.md" "$profile/SOUL.md"
        [[ -f $app_dir/hermes-config/config.yaml ]] && cp "$app_dir/hermes-config/config.yaml" "$profile/config.yaml"
        mkdir -p "$profile/skills/workspace-skills/plm" "$profile/webui/extensions"
        rsync -a --delete "$app_dir/skills/plm/" "$profile/skills/workspace-skills/plm/"
        rsync -a --delete "$app_dir/hermes-config/webui-extensions/noah/" "$profile/webui/extensions/noah/"
    done
fi

cd "$compose_dir"
docker compose -p plm up -d --force-recreate hermes-webui plm-nginx
docker restart plm-hermes-agent >/dev/null
if docker ps -a --format '{{.Names}}' | grep -qx plm-engine; then
    docker restart plm-engine >/dev/null
else
    "$compose_dir/run-engine.sh"
fi

sleep 3
docker ps --filter name=plm --format '{{.Names}}: {{.Status}}'
curl -fsS --max-time 10 http://127.0.0.1:8090/ >/dev/null
printf 'Deployed Biz PLM release %s at %s.\n' "$release_id" "$commit"