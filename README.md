# civicrm-code-age

How old is the code in [CiviCRM core](https://github.com/civicrm/civicrm-core)? This repo blames every
code line of civicrm-core, including the SVN history back to 2004, and renders the result as a static page:

- the age mix of the codebase on January 1st of every year since 2006 and today,
- survival curves: how long lines written in a given year stay unchanged, with their half-life,
- the lines alive today per year written,
- per area (`CRM/Contribute`, `ext/afform`, `templates/CRM/Event`, …) the share of each age band, the
  median year and a per-file drill-down.

## View

```sh
python3 -m http.server -d site 8000
# open http://localhost:8000
```

`site/data.json` is committed; the page loads it with `fetch`, so it needs a web server rather than `file://`.

## Reproduce

```sh
./analyze.sh                                   # clones civicrm-core from GitHub, branch master
./analyze.sh ~/src/civicrm-core master         # or reuse a local clone (shared, read-only)
JOBS=4 ./analyze.sh                            # parallelism, default: CPU count
```

Needs `git`, `bash`, `awk` and Python 3.11+. A run blames the branch tip and one snapshot per year
(`FIRST_SNAPSHOT_YEAR`, default 2006) and takes about 35 minutes on 10 cores. It works in a temporary bare clone,
never touches the source clone, and overwrites `site/data.json`.

## Method

- **Line age** is the author date of the commit that last changed the line (`git blame -w`). A 2008 line
  edited by one character in 2023 counts as 2023.
- **History before 2013.** civicrm-core's history starts on 2013-02-28 with "Import from SVN". `analyze.sh`
  fetches the archive [civicrm/civicrm-svn](https://github.com/civicrm/civicrm-svn) and grafts its `master`
  tip under the import commit (`git replace --graft`). That tip differs from the import by 57 lines.
- **Mechanical commits** listed in [`ignore-revs.txt`](ignore-revs.txt) are skipped via
  `--ignore-revs-file`: mass reformatting (including the April 2012 CRM-9979 runs and their reverts), short
  array syntax, copyright header rewrites and phpcs clean-ups.
- **Snapshots** repeat the blame on the last commit before January 1st of each year. Survival relates a
  cohort's lines at each snapshot to its size on the January 1st after its year; a changed line counts as gone.
- **Scope** is code only: `*.php`, `*.tpl`, `*.js`, `*.ts`, `*.html`, `*.css`, `*.scss`. Excluded are
  `sql/`, `xml/templates/`, generated `DAO/` classes, JSON and minified files, and the bundled libraries and
  CMS modules of the SVN era (`packages/`, `PEAR/`, `drupal/`, `joomla/`, `WordPress/`, `standalone/`, …).

## Limitations

- SVN branch work appears as `svn merge` commits on `master` and counts with the merge date, weeks to
  months after it was written.
- Code imported from other repositories counts with its import date because its earlier history is not
  linked: APIv4 (2019), civicrm-setup (2020), Flexmailer (2020), RiverLea (2022) and the schema conversion
  to `*.entityType.php` (2024). These areas look younger than they are.
- `ignore-revs.txt` covers mechanical commits with 800 or more changed lines, not every small one.

## Files

| Path | Purpose |
|---|---|
| `analyze.sh` | Clone, graft SVN history, blame in parallel, write `site/data.json` |
| `aggregate.py` | Fold blame output into per-file and per-snapshot line counts per year |
| `ignore-revs.txt` | Mechanical commits skipped by blame, each with date and subject |
| `site/index.html` | The page; no build step, no dependencies besides Google Fonts |
| `site/data.json` | Generated data: per file and per snapshot, lines per year from 2004 |

## License

[AGPL-3.0](LICENSE)
