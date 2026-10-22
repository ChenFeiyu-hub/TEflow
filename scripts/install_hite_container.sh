#!/usr/bin/env bash
# Download only. Does not change any existing Conda environment or launch HiTE.
set -euo pipefail
target=${1:?Usage: bash scripts/install_hite_container.sh /absolute/path/hite-3.3.3.sif}
engine=${APPTAINER:-apptainer}
[[ "$target" == /* && "$target" != *" "* ]] || { echo "Use an absolute image path without spaces" >&2; exit 2; }
[[ ! -e "$target" && ! -e "$target.partial" ]] || { echo "Existing image/partial download preserved; inspect it or use a new path" >&2; exit 2; }
command -v "$engine" >/dev/null || { echo "Install Apptainer on the server first; no root Docker daemon is required" >&2; exit 2; }
mkdir -p -- "$(dirname -- "$target")"
"$engine" pull "$target.partial" docker://kanghu/hite:3.3.3
"$engine" run --cleanenv "$target.partial" python /HiTE/main.py --help > "$target.help.txt" 2>&1
checksum=$(sha256sum "$target.partial" | cut -d ' ' -f 1)
reported=3.3.3
if ! grep -F 'HiTE, version 3.3.3' "$target.help.txt" >/dev/null; then
    if grep -F 'HiTE, version 3.3.2' "$target.help.txt" >/dev/null && \
       [[ "$checksum" == 4776bd6a1c0d8797f0e1e5febe385b157fb36a5de0615b2b7f8818672de74e55 ]]; then
        reported=3.3.2
        echo 'Recognized exact Zenodo image: release label 3.3.3, CLI version 3.3.2.'
    else
        tail -n 60 "$target.help.txt" >&2
        echo 'Unrecognized HiTE version/image combination; preserve the help log and image for review.' >&2
        exit 2
    fi
fi
mv -- "$target.partial" "$target"
sha256sum "$target" > "$target.sha256"
printf '{"release_label":"3.3.3","reported_version":"%s","sha256":"%s"}\n' "$reported" "$checksum" > "$target.identity.json"
printf '%s\n' "Image downloaded and CLI checked. Run teflow doctor --dependencies before genome analysis."
