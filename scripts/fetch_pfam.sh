#!/usr/bin/env bash
# Explicit download only; never called from a workflow stage.
set -euo pipefail
dest=${1:?Usage: bash scripts/fetch_pfam.sh /absolute/pfam-dir 37.0}
release=${2:?Specify a frozen Pfam release, e.g. 37.0}
[[ "$release" =~ ^[0-9]+\.[0-9]+$ ]] || { echo "Invalid release" >&2; exit 2; }
[[ ! -e "$dest/Pfam-A.hmm" && ! -e "$dest/Pfam-A.hmm.dat" ]] || { echo "Existing Pfam assets preserved; use a new directory" >&2; exit 2; }
mkdir -p "$dest"
base="https://ftp.ebi.ac.uk/pub/databases/Pfam/releases/Pfam${release}"
for name in Pfam-A.hmm Pfam-A.hmm.dat; do
  curl --fail --location --retry 3 "$base/$name.gz" -o "$dest/$name.gz.part"
  gzip -t "$dest/$name.gz.part"
  gzip -dc "$dest/$name.gz.part" > "$dest/$name.tmp"
  mv "$dest/$name.tmp" "$dest/$name"
done
hmmpress "$dest/Pfam-A.hmm"
printf '%s\n' "$base" > "$dest/SOURCE_URL.txt"
sha256sum "$dest"/Pfam-A.hmm* > "$dest/SHA256SUMS.txt"
