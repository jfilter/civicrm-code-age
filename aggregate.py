"""Fold blame output (path, commit, author time, lines) into per-file and per-snapshot line counts per year."""
import collections
import datetime
import json
import pathlib
import subprocess
import sys

Y0, Y1 = 2004, datetime.date.today().year

head_tsv, snapshot_dir, repo, ref, ignore_file = sys.argv[1:6]


def git(*args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def per_file_years(tsv):
    files = collections.defaultdict(lambda: [0] * (Y1 - Y0 + 1))
    for line in open(tsv):
        path, _commit, ts, n = line.rstrip("\n").split("\t")
        year = datetime.datetime.fromtimestamp(int(ts), datetime.UTC).year
        if not Y0 <= year <= Y1:
            sys.exit(f"{tsv}: {path} has a line from {year}, outside {Y0}-{Y1}")
        files[path][year - Y0] += int(n)
    return files


snapshots = []
for tsv in sorted(pathlib.Path(snapshot_dir).glob("*.tsv")):
    date, commit = tsv.stem.split("_")
    files = per_file_years(tsv)
    snapshots.append({"date": date, "commit": commit[:10], "files": len(files), "ys": [sum(c) for c in zip(*files.values())]})

ignored = [
    git("log", "-1", "--format=%h|%ad|%s", "--date=short", h).split("|", 2)
    for h in (l.strip() for l in open(ignore_file))
    if h and not h.startswith("#")
]
head = per_file_years(head_tsv)
meta = {
    "head": git("log", "-1", "--format=%h|%ad", "--date=short", ref).split("|"),
    "ref": ref,
    "y0": Y0,
    "y1": Y1,
    "ignored": ignored,
}
json.dump(
    {"meta": meta, "snapshots": snapshots, "files": sorted([p, v] for p, v in head.items())},
    sys.stdout,
    separators=(",", ":"),
)
