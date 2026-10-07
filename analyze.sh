#!/usr/bin/env bash
# Blame every code line of civicrm-core (with the pre-2013 SVN history grafted in) at the branch
# tip and on each January 1st, and write docs/data.json. Usage: ./analyze.sh [path or URL] [branch]
# Blame results are cached per commit in cache/, keyed by the blame and file-filter code and ignore-revs.txt.
set -euo pipefail

SRC=${1:-https://github.com/civicrm/civicrm-core.git}
REF=${2:-master}
JOBS=${JOBS:-$(getconf _NPROCESSORS_ONLN)}
FIRST_SNAPSHOT_YEAR=${FIRST_SNAPSHOT_YEAR:-2006}
HERE=$(cd "$(dirname "$0")" && pwd)
CACHE=${CACHE:-$HERE/cache}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

SVN_URL=https://github.com/civicrm/civicrm-svn.git
# "Import from SVN (r45945, r596)", the first content commit of civicrm-core
SVN_IMPORT=6a4880350680e1e4d20e5c8a622a791f926ca750
# Tip of civicrm-svn master; its code differs from the import by 57 lines
SVN_TIP=46df80d543362780c1661eb51aa32503e5ec53e5

clone_opts=(-q --bare --single-branch -b "$REF")
[[ -d $SRC ]] && clone_opts+=(--shared)
git clone "${clone_opts[@]}" "$SRC" "$WORK/repo"
git -C "$WORK/repo" fetch -q "$SVN_URL" master:refs/svn/master
git -C "$WORK/repo" replace --graft "$SVN_IMPORT" "$SVN_TIP"

blame_batch() {
  set -eo pipefail
  local f out
  out=$(mktemp "$OUT/XXXXXX")
  for f in "$@"; do
    # -C keeps the age of code moved between files changed in the same commit.
    # LC_ALL=C: old files carry Latin-1 bytes that make a UTF-8 awk abort
    git -C "$WORK/repo" blame -w -C --ignore-revs-file "$HERE/ignore-revs.txt" --line-porcelain "$COMMIT" -- "$f" \
      | LC_ALL=C awk -v f="$f" '/^[0-9a-f]{40} /{n[substr($1,1,10)]++} END{for(c in n) print f"\t"c"\t"n[c]}'
  done > "$out"
}
export -f blame_batch
export WORK HERE

# Code only: no data, message templates, generated files, minified assets, CMS modules, mockups or bundled
# libraries (packages/, jscalendar 2005-2009, a SugarCRM serializer, extension SDKs).
list_files() {
  git -C "$WORK/repo" ls-tree -r --name-only "$1" \
    | grep -E '\.(php|tpl|js|ts|html|css|scss)$' \
    | grep -vE '\.min\.(js|css)$|^sql/|^xml/templates/|^CRM/Upgrade/[^/]*\.msg_template/|/DAO/' \
    | grep -vE '\.civix\.php$|^CRM/Core/I18n/SchemaStructure' \
    | grep -vE '^(PEAR|packages|packages\.orig|mambo|modules|drupal|joomla|WordPress|standalone|l10n|mockups)/' \
    | grep -vE '/packages/|^js/calendar[^/]*\.js$|^js/lang/calendar-|^extern/contactserialize\.php$'
}

KEY=$({ declare -f blame_batch list_files; echo "$SVN_IMPORT $SVN_TIP"; cat "$HERE/ignore-revs.txt"; } | shasum | cut -c1-12)
mkdir -p "$CACHE/$KEY"

# blame_commit COMMIT: per file, line counts per commit, in $CACHE/$KEY/COMMIT.tsv.
blame_commit() {
  local tsv="$CACHE/$KEY/$1.tsv"
  [[ -f $tsv ]] && return
  export COMMIT=$1 OUT="$WORK/out"
  mkdir "$OUT"
  list_files "$1" | tr '\n' '\0' | xargs -0 -P "$JOBS" -n 40 bash -c 'blame_batch "$@"' _
  cat "$OUT"/* > "$tsv.tmp"
  mv "$tsv.tmp" "$tsv"
  rm -r "$OUT"
}

mkdir "$WORK/snapshots"
head=$(git -C "$WORK/repo" rev-parse "$REF")
echo "Blaming $REF (${head:0:10}) ..." >&2
blame_commit "$head"
for ((y = FIRST_SNAPSHOT_YEAR; y <= $(date +%Y); y++)); do
  c=$(git -C "$WORK/repo" rev-list -1 --first-parent --before="$y-01-01T00:00:00Z" "$REF")
  echo "Blaming snapshot $y-01-01 (${c:0:10}) ..." >&2
  blame_commit "$c"
  ln -s "$CACHE/$KEY/$c.tsv" "$WORK/snapshots/$y-01-01_$c.tsv"
done

python3 -I "$HERE/aggregate.py" "$CACHE/$KEY/$head.tsv" "$WORK/snapshots" "$WORK/repo" "$REF" "$HERE/ignore-revs.txt" \
  > "$HERE/docs/data.json"
