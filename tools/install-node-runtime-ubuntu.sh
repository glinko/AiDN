#!/usr/bin/env bash
# Install a pinned Node runtime below an operator-owned directory.
# The dashboard build must not depend on Ubuntu's older nodejs package.
set -euo pipefail

readonly DEFAULT_NODE_VERSION='v24.19.0'

usage() {
  cat <<'EOF'
Usage:
  install-node-runtime-ubuntu.sh --output-dir DIR [--version vX.Y.Z]

Downloads a pinned official Node Linux archive for x86_64 or arm64, verifies
its SHA-256 against the matching Node release manifest, and prints the runtime
directory. Existing matching installs are reused.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

valid_absolute_path() {
  [[ "$1" == /* && "$1" != *[[:space:]]* ]]
}

version="$DEFAULT_NODE_VERSION"
output_dir=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || die '--output-dir requires a value'
      output_dir="$2"
      shift 2
      ;;
    --version)
      [[ $# -ge 2 ]] || die '--version requires a value'
      version="$2"
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

[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die '--version must look like v24.19.0'
valid_absolute_path "$output_dir" || die '--output-dir must be an absolute path without spaces'

case "$(uname -m)" in
  x86_64|amd64) node_arch='x64' ;;
  aarch64|arm64) node_arch='arm64' ;;
  *) die "unsupported Node architecture: $(uname -m)" ;;
esac

command -v curl >/dev/null 2>&1 || die 'curl is required to install Node'
command -v sha256sum >/dev/null 2>&1 || die 'sha256sum is required to verify Node'
command -v tar >/dev/null 2>&1 || die 'tar is required to extract Node'

output_dir="${output_dir%/}"
mkdir -p "$output_dir"
archive_root="node-${version}-linux-${node_arch}"
target="$output_dir/$archive_root"
case "$target" in
  "$output_dir"/*) ;;
  *) die 'refusing to use a Node target outside --output-dir' ;;
esac

version_marker="$target/.aidn-node-version"
if [[ -x "$target/bin/node" && -f "$version_marker" && "$(cat "$version_marker")" == "$version" ]]; then
  [[ "$("$target/bin/node" --version)" == "$version" ]] || die "existing Node runtime does not match $version"
  printf '%s\n' "$target"
  exit 0
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "$temporary_dir"' EXIT
archive="$archive_root.tar.xz"
release_url="https://nodejs.org/dist/$version"

curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
  "$release_url/SHASUMS256.txt" -o "$temporary_dir/SHASUMS256.txt"
expected_sha="$(awk -v archive="$archive" '$2 == archive { print $1; exit }' "$temporary_dir/SHASUMS256.txt")"
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || die "Node release manifest does not contain $archive"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
  "$release_url/$archive" -o "$temporary_dir/$archive"
actual_sha="$(sha256sum "$temporary_dir/$archive" | awk '{ print $1 }')"
[[ "$actual_sha" == "$expected_sha" ]] || die "Node archive checksum mismatch for $archive"

tar -xJf "$temporary_dir/$archive" -C "$temporary_dir"
[[ -x "$temporary_dir/$archive_root/bin/node" ]] || die 'Node archive did not contain the expected runtime'

# `target` was derived from a validated output directory and architecture.
rm -rf -- "$target"
mv "$temporary_dir/$archive_root" "$target"
printf '%s\n' "$version" > "$version_marker"
chmod 600 "$version_marker"
[[ "$("$target/bin/node" --version)" == "$version" ]] || die "installed Node runtime does not match $version"
printf '%s\n' "$target"
