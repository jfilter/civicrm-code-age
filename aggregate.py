"""Fold blame output (path, commit, lines) into per-file and per-snapshot line counts per year.

A line's year is when the commit that last changed it reached ref, not its author date."""
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


def landing_years():
    """Year each commit reached ref: the committer year of the first-parent commit that brought it in."""
    parents = {}
    for line in git("rev-list", "--parents", ref).splitlines():
        c, *ps = line.split()
        parents[c] = ps
    landed = {}
    for line in reversed(git("log", "--first-parent", "--format=%H %ct", ref).splitlines()):
        f, ct = line.split()
        year = datetime.datetime.fromtimestamp(int(ct), datetime.UTC).year
        stack = [f]
        while stack:
            c = stack.pop()
            if c[:10] not in landed:
                landed[c[:10]] = year
                stack.extend(parents[c])
    return landed


LANDED = landing_years()


def read_blame(tsv):
    files = collections.defaultdict(lambda: [0] * (Y1 - Y0 + 1))
    for line in open(tsv):
        path, commit, n = line.rstrip("\n").split("\t")
        if commit not in LANDED:
            sys.exit(f"{tsv}: {path} blames {commit}, which is not on {ref}")
        year = LANDED[commit]
        if not Y0 <= year <= Y1:
            sys.exit(f"{tsv}: {path} has a line from {year}, outside {Y0}-{Y1}")
        files[path][year - Y0] += int(n)
    return files


snapshots = []
for tsv in sorted(pathlib.Path(snapshot_dir).glob("*.tsv")):
    date, commit = tsv.stem.split("_")
    files = read_blame(tsv)
    ys = [sum(c) for c in zip(*files.values())]
    if any(ys[int(date[:4]) - Y0 :]):
        sys.exit(f"{tsv}: snapshot holds lines that reached {ref} on or after {date}")
    snapshots.append({"date": date, "commit": commit[:10], "files": len(files), "ys": ys})

ignored = [
    git("log", "-1", "--format=%h|%ad|%s", "--date=short", h).split("|", 2)
    for h in (l.strip() for l in open(ignore_file))
    if h and not h.startswith("#")
]
head = read_blame(head_tsv)
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
