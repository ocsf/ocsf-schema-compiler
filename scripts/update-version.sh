#!/usr/bin/env bash
# Updates Python package version when publishing via GitHub Workflows.
# Used by .github/workflows/publish.yaml and .github/workflows/test-publish.yaml.

set -euo pipefail

file="${1:?usage: $0 path/to/__init__.py TAG}"
tag="${2:?usage: $0 path/to/__init__.py TAG}"

package_version="${tag#v}"

tmp="$(mktemp)"
sed -E "s/^__version__[[:space:]]*=[[:space:]]*\"[^\"]*\"/__version__ = \"${package_version}\"/" \
  "$file" > "$tmp"
mv "$tmp" "$file"
