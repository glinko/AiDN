#!/usr/bin/env bash
# Build the React operator dashboard into the Python package's static directory.
set -euo pipefail

readonly PNPM_VERSION='11.16.0'

usage() {
  cat <<'EOF'
Usage:
  build-operator-dashboard.sh --project-root DIR --node-root DIR --tooling-dir DIR

Builds web/operator-dashboard with a pinned local pnpm and atomically stages
the resulting static files below src/aidn_hypervisor/static/react-dashboard.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

valid_absolute_path() {
  [[ "$1" == /* && "$1" != *[[:space:]]* ]]
}

project_root=''
node_root=''
tooling_dir=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      [[ $# -ge 2 ]] || die '--project-root requires a value'
      project_root="$2"
      shift 2
      ;;
    --node-root)
      [[ $# -ge 2 ]] || die '--node-root requires a value'
      node_root="$2"
      shift 2
      ;;
    --tooling-dir)
      [[ $# -ge 2 ]] || die '--tooling-dir requires a value'
      tooling_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

for value in "$project_root" "$node_root" "$tooling_dir"; do
  valid_absolute_path "$value" || die 'all paths must be absolute and contain no spaces'
done
project_root="${project_root%/}"
node_root="${node_root%/}"
tooling_dir="${tooling_dir%/}"

dashboard_dir="$project_root/web/operator-dashboard"
target="$project_root/src/aidn_hypervisor/static/react-dashboard"
expected_target="$project_root/src/aidn_hypervisor/static/react-dashboard"
[[ "$target" == "$expected_target" ]] || die 'refusing to stage assets outside the Hypervisor static directory'
[[ -x "$node_root/bin/node" ]] || die "Node runtime is missing: $node_root/bin/node"
[[ -x "$node_root/bin/npm" ]] || die "npm is missing from Node runtime: $node_root/bin/npm"
[[ -f "$dashboard_dir/package.json" && -f "$dashboard_dir/pnpm-lock.yaml" ]] || {
  die "React dashboard package is incomplete: $dashboard_dir"
}

node_major="$("$node_root/bin/node" -p 'process.versions.node.split(".")[0]')"
[[ "$node_major" =~ ^[0-9]+$ ]] && (( node_major >= 20 )) || die 'React dashboard requires Node 20 or newer'

pnpm_root="$tooling_dir/pnpm-$PNPM_VERSION"
pnpm_bin="$pnpm_root/bin/pnpm"
mkdir -p "$tooling_dir"
if [[ ! -x "$pnpm_bin" || "$(PATH="$node_root/bin:$PATH" "$pnpm_bin" --version 2>/dev/null || true)" != "$PNPM_VERSION" ]]; then
  case "$pnpm_root" in
    "$tooling_dir"/*) ;;
    *) die 'refusing to install pnpm outside --tooling-dir' ;;
  esac
  rm -rf -- "$pnpm_root"
  PATH="$node_root/bin:$PATH" "$node_root/bin/npm" install --global --prefix "$pnpm_root" \
    --ignore-scripts --no-audit --no-fund "pnpm@$PNPM_VERSION"
fi
[[ -x "$pnpm_bin" ]] || die 'pinned pnpm installation did not produce an executable'

export PATH="$node_root/bin:$pnpm_root/bin:$PATH"
"$pnpm_bin" --dir "$dashboard_dir" install --frozen-lockfile
"$pnpm_bin" --dir "$dashboard_dir" build

[[ -f "$dashboard_dir/dist/index.html" ]] || die 'React dashboard build did not produce index.html'
staging="$target.next.$$"
backup="$target.previous.$$"
case "$staging" in
  "$project_root"/src/aidn_hypervisor/static/react-dashboard.next.*) ;;
  *) die 'refusing to use an unsafe dashboard staging directory' ;;
esac
rm -rf -- "$staging" "$backup"
mkdir -p "$staging"
cp -a "$dashboard_dir/dist/." "$staging/"
[[ -f "$staging/index.html" ]] || die 'dashboard staging is incomplete'

# A bootstrap invokes this before the Hypervisor starts. On a live upgrade the
# old directory remains intact until the new build has fully completed.
if [[ -d "$target" ]]; then
  mv "$target" "$backup"
fi
if ! mv "$staging" "$target"; then
  [[ -d "$backup" ]] && mv "$backup" "$target"
  die 'could not activate the React dashboard assets'
fi
rm -rf -- "$backup"
asset_count="$(find "$target" -type f | wc -l | tr -d '[:space:]')"
printf '{"status":"ok","dashboard":"%s","asset_count":%s,"node_version":"%s","pnpm_version":"%s"}\n' \
  "$target" "$asset_count" "$("$node_root/bin/node" --version)" "$PNPM_VERSION"
