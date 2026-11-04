#!/usr/bin/env python3
"""Follow every code line of civicrm-core (with the pre-2013 SVN history grafted in) from the first of each month
to the branch tip, count lines per year of their last change, and write docs/data.json, docs/history.json and
docs/who.json (lines per release and author).

A line's year is when the change that produced it reached ref. The first snapshot takes it from blame. After that a
line keeps its year while it is unchanged (git diff -w); a changed or new line keeps an old year only when blame -C
over the month traces it to a line that vanished in the same step (a move), and otherwise gets the year its commit
reached ref. Blame results are cached per step in cache/, keyed by the blame code, the file filter and the ignore list.
"""
import argparse
import bisect
import collections
import concurrent.futures
import datetime
import gzip
import hashlib
import inspect
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib

HERE = pathlib.Path(__file__).resolve().parent
IGNORE = HERE / "ignore-revs.txt"
MAILMAP = HERE / "mailmap"
SVN_URL = "https://github.com/civicrm/civicrm-svn.git"
# "Import from SVN (r45945, r596)", the first content commit of civicrm-core
SVN_IMPORT = "6a4880350680e1e4d20e5c8a622a791f926ca750"
# Tip of civicrm-svn master; its code differs from the import by 57 lines
SVN_TIP = "46df80d543362780c1661eb51aa32503e5ec53e5"
Y0, Y1 = 2004, datetime.date.today().year

# Code only: no data, message templates, generated files, minified assets, CMS modules, mockups or bundled
# libraries (packages/, jscalendar 2005-2009, a SugarCRM serializer, extension SDKs).
CODE = re.compile(r"\.(php|tpl|js|ts|html|css|scss)$")
NOT_CODE = re.compile(
    r"\.min\.(js|css)$|^sql/|^xml/templates/|^CRM/Upgrade/[^/]*\.msg_template/|/DAO/"
    r"|\.civix\.php$|^CRM/Core/I18n/SchemaStructure"
    r"|^(PEAR|packages|packages\.orig|mambo|modules|drupal|joomla|WordPress|standalone|l10n|mockups)/"
    r"|/packages/|^js/calendar[^/]*\.js$|^js/lang/calendar-|^extern/contactserialize\.php$"
)
HEADER = re.compile(rb"^([0-9a-f]{40}) (\d+) \d+")
HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

repo = ""
# Origins of lines: (year, commit, position of the first-parent commit that brought the change to ref); a line's
# state is an index into ORIGINS.
# INTRODUCED counts the lines each origin brought in, from the first snapshot on.
ORIGINS, ORIGIN_IDS, INTRODUCED = [], {}, collections.Counter()


def introduce(commit, year, pos):
    key = (year, commit, pos)
    if key not in ORIGIN_IDS:
        ORIGIN_IDS[key] = len(ORIGINS)
        ORIGINS.append(key)
    INTRODUCED[ORIGIN_IDS[key]] += 1
    return ORIGIN_IDS[key]


def git(*args, text=True):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=text).stdout


def setup(src, ref):
    """A bare clone in the cache, refreshed from src, with the SVN history grafted under the import commit."""
    if not pathlib.Path(repo).exists():
        subprocess.run(["git", "clone", "-q", "--bare", "--single-branch", "-b", ref, src, repo], check=True)
    else:
        git("fetch", "-q", "--force", src, f"{ref}:{ref}")
    if subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", "refs/svn/master"],
                      capture_output=True).returncode:
        git("fetch", "-q", SVN_URL, "master:refs/svn/master")
    git("fetch", "-q", "--force", src, "refs/tags/*:refs/tags/*")
    # Release branches X.Y, for the release candidate that has no X.Y.0 tag yet
    heads = [l.split("\t")[1] for l in git("ls-remote", "--heads", src).splitlines()]
    want = {f"refs/release/{h[11:]}": h for h in heads if re.fullmatch(r"refs/heads/\d+\.\d+", h)}
    for r in set(git("for-each-ref", "--format=%(refname)", "refs/release").split()) - want.keys():
        git("update-ref", "-d", r)  # branch deleted upstream
    git("fetch", "-q", "--force", src, *[f"{h}:{r}" for r, h in want.items()])
    if subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", "refs/svn/v1.0"],
                      capture_output=True).returncode:
        git("fetch", "-q", SVN_URL, "refs/heads/v*:refs/svn/v*")
    git("replace", "-f", "--graft", SVN_IMPORT, SVN_TIP)


def code_files(commit):
    paths = git("ls-tree", "-r", "-z", "--name-only", commit, text=False).split(b"\0")
    paths = (p.decode("utf-8", "surrogateescape") for p in paths if p)
    return sorted(p for p in paths if CODE.search(p) and not NOT_CODE.search(p))


def blame(path, commit, prev):
    """Per line: [commit, origin file, origin line], where blame -C over prev..commit traces it. Lines that were
    there before the range carry the boundary commit, prefixed with "^". Stored as runs: [commit, file, first, n]."""
    rev = f"{prev}..{commit}" if prev else commit
    out = subprocess.run(
        ["git", "-C", repo, "blame", "-w", "-C", "--root", "--ignore-revs-file", str(IGNORE), "--line-porcelain",
         rev, "--", path], check=True, capture_output=True).stdout
    runs, c, o, fn, bound = [], None, 0, "", False
    for line in out.split(b"\n"):
        if line.startswith(b"\t"):
            k = ("^" if bound else "") + c
            if runs and runs[-1][0] == k and runs[-1][1] == fn and runs[-1][2] + runs[-1][3] == o:
                runs[-1][3] += 1
            else:
                runs.append([k, fn, o, 1])
        elif m := HEADER.match(line):
            c, o, bound = m[1].decode(), int(m[2]), False
        elif line == b"boundary":
            bound = True
        elif line.startswith(b"filename "):
            fn = line[9:].decode("utf-8", "surrogateescape")
            fn = "" if fn == path else fn
    return runs


def blame_step(prev, commit, files, jobs):
    """Blame runs of every file that changed in prev..commit (all files without prev), cached per step."""
    tsv = cache / f"{prev or 'root'}..{commit}.tsv.gz"
    if not tsv.exists():
        todo = files
        if prev:
            changed = git("diff", "-z", "--no-renames", "--name-only", prev, commit, text=False).split(b"\0")
            changed = {p.decode("utf-8", "surrogateescape") for p in changed if p}
            todo = [p for p in files if p in changed]
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            results = pool.map(lambda p: (p, blame(p, commit, prev)), todo)
            with gzip.open(f"{tsv}.tmp", "wt", encoding="utf-8", errors="surrogateescape") as out:
                for p, runs in results:
                    for c, fn, first, n in runs or [["", "", 0, 0]]:  # an empty file is one empty run
                        out.write(f"{p}\t{c}\t{fn}\t{first}\t{n}\n")
        os.replace(f"{tsv}.tmp", tsv)
    rows = collections.defaultdict(list)
    with gzip.open(tsv, "rt", encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            p, c, fn, first, n = line.rstrip("\n").split("\t")
            rows[p] += [(c, fn or p, o) for o in range(int(first), int(first) + int(n))]  # creates empty files too
    return rows


def landing(ref):
    """Per commit, the year it reached ref and the position of the first-parent commit that brought it in."""
    parents = {}
    for line in git("rev-list", "--parents", ref).splitlines():
        c, *ps = line.split()
        parents[c] = ps
    landed = {}
    for i, line in enumerate(reversed(git("log", "--first-parent", "--format=%H %ct", ref).splitlines())):
        f, ct = line.split()
        year = datetime.datetime.fromtimestamp(int(ct), datetime.UTC).year
        stack = [f]
        while stack:
            c = stack.pop()
            if c not in landed:
                landed[c] = (year, i)
                stack.extend(parents[c])
    return landed


def landed(commit, where):
    if commit not in LANDED:
        sys.exit(f"{where} blames {commit}, which is not on the branch")
    year, pos = LANDED[commit]
    if not Y0 <= year <= Y1:
        sys.exit(f"{where} has a line from {year}, outside {Y0}-{Y1}")
    return year, pos


def hunks(old, new, paths):
    """Per path, the changed line ranges (old start, old count, new start, new count) between two commits."""
    out = {}
    paths = sorted(paths)
    for i in range(0, len(paths), 500):
        diff = git("--literal-pathspecs", "diff", "-w", "-a", "-U0", "--no-renames", "--no-color", "--no-ext-diff",
                   "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", old, new, "--", *paths[i : i + 500],
                   text=False)
        path, header = None, False
        for line in diff.splitlines():
            if line.startswith(b"diff --git "):
                path, header = None, True
            elif header and line.startswith(b"+++ b/"):
                path = line[6:].rstrip(b"\t").decode("utf-8", "surrogateescape")
                out.setdefault(path, [])
            elif m := HUNK.match(line):
                if path is None:
                    sys.exit(f"diff {old[:10]}..{new[:10]}: hunk without a file")
                header = False
                out[path].append(tuple(int(x) if x is not None else 1 for x in m.groups()))
    return out


def map_line(hs, n):
    """Line n (1-based) of the old side through hunks hs to its 0-based index on the new side; None if changed."""
    i, shift = n - 1, 0
    for a, b, _, d in hs:
        a = a - 1 if b else a  # 0-based start of the removed lines, or the index an insertion goes before
        if a + b > i:
            return None if a <= i else i + shift
        shift += d - b
    return i + shift


def step(state, prev, commit, files, rows, stats):
    """Carry state (path -> origin id per line) at prev forward to commit."""
    gone = {}  # (path, line index at prev) -> [year, used] for lines that vanished in this step
    fresh = []  # (path, line index, origin, lines removed by the same hunk) of changed and new lines
    diffs = hunks(prev, commit, [p for p in rows if p in state])
    new_state = {p: state[p] for p in files if p not in rows}

    def vanish(p, start, end):
        out = []
        for i in range(start, end):
            gone[p, i] = g = [state[p][i], False]
            out.append(g)
        return out

    for p in sorted(set(state) - set(files)):
        vanish(p, 0, len(state[p]))
    for p, keys in rows.items():
        lines = [None] * len(keys)
        if p in state:
            old, o, n = state[p], 0, 0
            for a, b, c, d in diffs.get(p, []):
                a, c = (a - 1 if b else a), (c - 1 if d else c)
                if a - o != c - n or a + b > len(old) or c + d > len(lines):
                    sys.exit(f"{p}: diff {prev[:10]}..{commit[:10]} does not line up with the blame")
                lines[n : n + a - o] = old[o:a]
                removed = vanish(p, a, a + b)
                fresh += [(p, j, keys[j], removed) for j in range(c, c + d)]
                o, n = a + b, c + d
            if len(old) - o != len(lines) - n:
                sys.exit(f"{p}: {len(old)} lines at {prev[:10]}, {len(lines)} at {commit[:10]}, diff disagrees")
            lines[n:] = old[o:]
        else:
            fresh += [(p, j, keys[j], []) for j in range(len(lines))]
        new_state[p] = lines

    # Boundary lines from a side branch point into a commit older than prev: map them through its diff to prev.
    side = collections.defaultdict(set)
    for _, _, (c, fn, _), _ in fresh:
        if c.startswith("^") and c[1:] != prev and fn in state:
            side[c[1:]].add(fn)
    side_hunks = {b: hunks(b, prev, fns) for b, fns in side.items()}

    def origin(c, fn, o):
        if fn not in state:
            return None
        if c[1:] == prev:
            return fn, o - 1
        i = map_line(side_hunks[c[1:]].get(fn, []), o)
        stats["side"] += 1
        return None if i is None else (fn, i)

    (now, here), after = landed(commit, commit), landed(prev, prev)[1]
    reformatted = set()  # files an ignored commit of this step changed
    for c in IGNORED:
        if after < LANDED.get(c, (0, -1))[1] <= here:
            reformatted.update(git("diff-tree", "--no-commit-id", "-r", "-z", "--name-only", "--root", c).split("\0"))

    def take(candidates):
        for g in candidates:
            if not g[1]:
                g[1] = True
                return g[0]

    # A changed line from before the range is a move when it traces to a line that vanished in this step. Else, in
    # a file an ignored commit changed, it is a rewrite that takes the year of a line its hunk removed; else new.
    # A copy is new code of this year, but keeps the commit and landing position, hence author and release, of its
    # source line.
    rest = []
    for p, j, (c, fn, o), removed in fresh:
        year, pos = landed(c.lstrip("^"), f"{p} at {commit[:10]}")
        if (pos > after) == c.startswith("^"):
            sys.exit(f"{p} at {commit[:10]}: {c[:11]} is {'inside' if pos > after else 'outside'} the step")
        if pos > after:
            new_state[p][j] = introduce(c, year, pos)
            stats["new"] += 1
        elif (k := origin(c, fn, o)) in gone and (i := take([gone[k]])) is not None:
            new_state[p][j] = i
            stats["moved"] += 1
        else:
            src = state[k[0]][k[1]] if k else None
            rest.append((p, j, src, removed if p in reformatted else []))
    for p, j, src, removed in rest:
        i = take(removed)
        if i is None:
            # a copy whose source line is unknown has no commit and lands at the end of this step
            i = introduce(None, now, here) if src is None else introduce(ORIGINS[src][1], now, ORIGINS[src][2])
            stats["copied" if src is not None else "copied from unknown"] += 1
        else:
            stats["rewritten"] += 1
        new_state[p][j] = i
    stats["removed"] += sum(not used for _, used in gone.values())
    return new_state


def counts(state):
    files = {}
    for p, years in state.items():
        ys = [0] * (Y1 - Y0 + 1)
        for i in years:
            ys[ORIGINS[i][0] - Y0] += 1
        files[p] = ys
    return files


def trim(ys):
    n = len(ys)
    while n and not ys[n - 1]:
        n -= 1
    return ys[:n]


def snapshots(ref, first_year, until):
    """The last first-parent commit before the first of each month, as git rev-list --before picks it."""
    chain = [line.split() for line in git("log", "--first-parent", "--format=%H %ct", ref).splitlines()]
    out, today = [], datetime.date.today()
    for y in range(first_year, today.year + 1):
        for m in range(1, 13):
            date = f"{y}-{m:02}-01"
            if date > today.isoformat() or (until and date[:7] > until):
                return out
            t = datetime.datetime(y, m, 1, tzinfo=datetime.UTC).timestamp()
            c = next((c for c, ct in chain if int(ct) <= t), None)
            if c:
                out.append((date, c))
    return out


RELEASE_TAG = re.compile(r"\d+\.\d+\.0|4\.7\.\d+")  # 4.7.x shipped monthly from master


def releases(ref):
    """Versions in version order as (name, last first-parent position they ship, branch date, release date): the
    tags X.Y.0 and 4.7.x, release branches X.Y without such a tag as "X.Y (rc)", and the SVN release branches vX.Y.
    A release ships ref up to the commit it branched from."""
    lines = git("log", "--first-parent", "--format=%H %cs", ref).splitlines()
    at = {c: (len(lines) - 1 - i, d) for i, (c, d) in enumerate(l.split() for l in lines)}
    refs = [(t, t, git("log", "-1", "--format=%cs", t).strip()) for t in git("tag").split() if RELEASE_TAG.fullmatch(t)]
    refs += [(r[10:], r, None) for r in git("for-each-ref", "--format=%(refname)", "refs/svn").split()
             if re.fullmatch(r"refs/svn/v\d+\.\d+", r)]
    tagged = {t for t, _, _ in refs}
    refs += [(r[13:] + ".0", r, None) for r in git("for-each-ref", "--format=%(refname)", "refs/release").split()
             if r[13:] + ".0" not in tagged]
    out = []
    for name, r, released in refs:
        with subprocess.Popen(["git", "-C", repo, "rev-list", "--first-parent", r], stdout=subprocess.PIPE, text=True) as log:
            fork = next((c for c in map(str.strip, log.stdout) if c in at), None)
            log.kill()
        if fork is None:
            sys.exit(f"{r} does not branch from {ref}")
        v = tuple(map(int, name.split(".")))
        name = name.removesuffix(".0") if len(v) == 3 and name != "4.7.0" else name
        out.append((v, name + (" (rc)" if r.startswith("refs/release/") else ""), *at[fork], released))
    return [o[1:] for o in sorted(out)]


def release_of(rels):
    """Position on ref -> index of the first release in version order that ships it, len(rels) if none does yet."""
    by_pos, best = [], len(rels)
    for pos, i in sorted(((r[1], i) for i, r in enumerate(rels)), reverse=True):
        best = min(best, i)
        by_pos.append((pos, best))
    by_pos.reverse()
    keys = [p for p, _ in by_pos]
    return lambda pos: by_pos[k][1] if (k := bisect.bisect_left(keys, pos)) < len(keys) else len(rels)


def authors(ref):
    """Commit -> author index, and the author names. Identities that share an e-mail address or a full name are one
    author, as is an address whose local part spells a full name (jane.doe@), and mailmap joins the rest. The name is
    the most frequent full name."""
    rows = [l.split("\0") for l in git("-c", f"mailmap.file={MAILMAP}", "log", "--format=%H%x00%aN%x00%aE", ref).splitlines()]
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = x = parent[parent[x]]
        return x

    def full(name):
        name = " ".join(re.sub(r"\(.*?\)", "", name).lower().split())
        return "n:" + name if " " in name else None

    for _, name, mail in rows:
        mail = mail.lower()
        local = full(re.sub(r"[._-]", " ", mail.split("@")[0]))
        for other in filter(None, [full(name), local]):
            parent[find(other)] = find("e:" + mail)
    names = collections.defaultdict(collections.Counter)
    for _, name, mail in rows:
        names[find("e:" + mail.lower())][name] += 1
    index, out = {}, []
    for root, cnt in sorted(names.items(), key=lambda kv: -kv[1].total()):
        index[root] = len(out)
        out.append(max(cnt, key=lambda n: (" " in n.strip(), cnt[n])))
    return {c: index[find("e:" + mail.lower())] for c, _, mail in rows}, out


# Age bands and light-theme colours of docs/common.js and docs/style.css, oldest first.
BANDS = [(2008, "0d366b"), (2012, "184f95"), (2017, "2a78d6"), (2021, "5598e7"), (9999, "86b6ef")]


def preview(snapshots, path, w=1200, h=630, pad=60):
    """Link preview image: lines per age band at every snapshot, as stacked columns, written as a PNG."""
    bg, cols = bytes.fromhex("f7f8fa"), [bytes.fromhex(c) for _, c in BANDS]
    stacks = []
    for s in snapshots:
        per = [0] * len(BANDS)
        for k, n in enumerate(s["ys"]):
            per[next(b for b, (to, _) in enumerate(BANDS) if Y0 + k <= to)] += n
        stacks.append(per)
    top = max(map(sum, stacks))
    rows = [[bg] * w for _ in range(h)]
    for x in range(pad, w - pad):
        y = h - pad
        for n, c in zip(stacks[(x - pad) * len(stacks) // (w - 2 * pad)], cols):
            dy = round(n * (h - 2 * pad) / top)
            for yy in range(y - dy, y):
                rows[yy][x] = c
            y -= dy
    raw = b"".join(b"\0" + b"".join(r) for r in rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    global repo, cache, LANDED, IGNORED
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", nargs="?", default="https://github.com/civicrm/civicrm-core.git", help="path or URL")
    ap.add_argument("ref", nargs="?", default="master")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--first-year", type=int, default=2006)
    ap.add_argument("--until", metavar="YYYY-MM", help="stop after this snapshot and skip the branch tip")
    ap.add_argument("--cache", type=pathlib.Path, default=HERE / "cache")
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "docs" / "data.json")
    args = ap.parse_args()
    if pathlib.Path(args.src).is_dir():
        args.src = str(pathlib.Path(args.src).resolve())

    repo = str(args.cache / "repo.git")
    args.cache.mkdir(exist_ok=True)
    setup(args.src, args.ref)
    key = hashlib.sha1("\n".join(
        [inspect.getsource(blame), inspect.getsource(blame_step), CODE.pattern, NOT_CODE.pattern, SVN_IMPORT, SVN_TIP, IGNORE.read_text()]
    ).encode()).hexdigest()[:12]
    cache = args.cache / key
    cache.mkdir(exist_ok=True)
    for d in args.cache.iterdir():  # blame results under an older key can never be used again
        if d.is_dir() and d.name not in (key, "repo.git"):
            shutil.rmtree(d)
    LANDED = landing(args.ref)
    IGNORED = [h for h in (l.strip() for l in IGNORE.read_text().splitlines()) if h and not h.startswith("#")]

    steps = snapshots(args.ref, args.first_year, args.until)
    if not args.until:
        steps.append(("head", git("rev-parse", args.ref).strip()))
    stats, done, state, prev = collections.Counter(), [], None, None
    before, paths, history, months, seen, used = {}, {}, [], [], [0, 0], set()
    for date, commit in steps:
        t = time.monotonic()
        files = code_files(commit)
        rows = blame_step(prev, commit, files, args.jobs)
        used.add(f"{prev or 'root'}..{commit}.tsv.gz")
        if state is None:
            state = {p: [introduce(c, *landed(c, f"{p} at {commit[:10]}")) for c, _, _ in rows[p]] for p in files}
        else:
            state = step(state, prev, commit, files, rows, stats)
        print(f"{date} {commit[:10]}: {len(rows)} files blamed, {time.monotonic() - t:.1f}s", file=sys.stderr)
        prev = commit
        total = [INTRODUCED.total(), stats["removed"]]
        months.append([date, total[0] - seen[0], total[1] - seen[1]])
        seen = total
        if date == "head":
            break
        files = counts(state)
        if not files:
            sys.exit(f"{date}: no code files")
        ys = [sum(c) for c in zip(*files.values())]
        # Snapshot Y-01-01 may hold nothing from year Y on; Y-MM-01 nothing after year Y.
        if any(ys[int(date[:4]) - Y0 + (date[5:7] != "01") :]):
            sys.exit(f"{date}: snapshot holds lines that reached {args.ref} on or after {date}")
        # A year's code can only shrink once the year is over.
        for s in done:
            if s["date"][5:7] == "01":
                grown = [Y0 + i for i in range(int(s["date"][:4]) - Y0) if ys[i] > s["ys"][i]]
                if grown:
                    sys.exit(f"{date}: lines from {grown} outnumber those on {s['date']}")
        # Per-file counts as changes against the previous snapshot: [path index, ys without trailing zeros],
        # [path index] for a removed file. Replaying them from the first snapshot rebuilds any month.
        delta = [[paths.setdefault(p, len(paths)), trim(v)] for p, v in files.items() if before.get(p) != v]
        delta += [[paths[p]] for p in before if p not in files]
        before = files
        history.append(sorted(delta))
        done.append({"date": date, "commit": commit[:10], "files": len(files), "ys": ys})
    print(f"changed lines after the first snapshot: {dict(stats)}", file=sys.stderr)
    if not args.until:  # steps to an earlier tip are never asked for again
        for f in cache.glob("*.tsv.gz"):
            if f.name not in used:
                f.unlink()

    ignored = [git("log", "-1", "--format=%h|%ad|%s", "--date=short", h).strip().split("|", 2) for h in IGNORED]
    meta = {
        "head": git("log", "-1", "--format=%h|%ad", "--date=short", prev).strip().split("|"),
        "ref": args.ref,
        "y0": Y0,
        "y1": Y1,
        "ignored": ignored,
    }
    with open(args.out, "w") as f:
        json.dump({"meta": meta, "snapshots": done, "files": sorted([p, v] for p, v in counts(state).items())},
                  f, separators=(",", ":"))

    with open(args.out.with_name("history.json"), "w") as f:
        json.dump({"paths": list(paths), "deltas": history}, f, separators=(",", ":"))
    preview(done, args.out.with_name("og.png"))

    # Lines alive at the tip and lines introduced since the first snapshot, per release, author and year (offset
    # from Y0) the change reached ref.
    rels = releases(args.ref)
    rel, (author, names) = release_of(rels), authors(args.ref)
    author[None] = len(names)
    names.append("Unknown (copied code)")
    # the year the commit landed, which for a copy is the year of its source line
    who = [(rel(pos), author[c], (year if c is None else LANDED[c][0]) - Y0) for year, c, pos in ORIGINS]
    alive = []
    for p, ids in sorted(state.items()):
        per = collections.Counter(who[i] for i in ids)
        alive.append([p, [x for k, n in sorted(per.items()) for x in (*k, n)]])
    introduced = collections.Counter()
    for i, n in INTRODUCED.items():
        introduced[who[i]] += n
    with open(args.out.with_name("who.json"), "w") as f:
        json.dump({"releases": [[name, at, released] for name, _, at, released in rels], "authors": names, "unknown": author[None],
                   "files": alive, "introduced": [[*k, n] for k, n in sorted(introduced.items())],
                   "months": months}, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
