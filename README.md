# civicrm-code-age

How old is the code in [CiviCRM core](https://github.com/civicrm/civicrm-core)? This repo blames every
code line of civicrm-core, including the SVN history back to 2004, and renders the result as a static page:

- the age mix of the codebase on the first of every month since 2006 and today,
- survival curves: how long lines that reached `master` in a given year stay unchanged, with their half-life,
- the lines alive today per year of last change,
- per area (`CRM/Contribute`, `ext/afform`, `templates/CRM/Event`, …) the share of each age band, the
  median year and a per-file drill-down.

## View

**https://jfilter.github.io/civicrm-code-age/**, or locally:

```sh
python3 -m http.server -d docs 8000
# open http://localhost:8000
```

`docs/data.json` is committed; the page loads it with `fetch`, so it needs a web server rather than `file://`.

## Reproduce

```sh
./analyze.py                                   # civicrm-core from GitHub, branch master
./analyze.py ~/src/civicrm-core master         # or fetch from a local clone
./analyze.py --jobs 4                          # parallel blames, default: CPU count
./analyze.py --until 2013-06                   # stop early, without the branch tip
```

Needs `git` and Python 3.11+, nothing else. A run follows the code from one snapshot per month since
`--first-year` (default 2006) to the branch tip and takes about 25 minutes on 10 cores without a cache. It keeps a bare clone
in `cache/repo.git`, fetches the branch into it on every run, never writes to the source clone, and
overwrites `docs/data.json`.

Blame results are cached per month in `cache/` (`--cache` to move it), keyed by the blame code, the file
filter and `ignore-revs.txt`. A later run blames only the months since the last one; a change to the blame,
the filter or the ignore list starts a fresh key and blames everything again.

## Method

- **Line age** is when the change that produced a line reached `master`: the committer date of the
  first-parent commit that merged it. Author dates are not used, so work on branches and in pull requests
  counts with its merge date, as SVN branches merged with `svn merge` always did. A 2008 line edited by one
  character in 2023 counts as 2023.
- **Line tracking.** The first snapshot takes each line's age from `git blame -w -C`. From then on
  `analyze.py` follows every line from month to month. A line that `git diff -w` shows unchanged keeps its
  year. Changes are measured between snapshots, so a change reverted within the same month
  leaves no trace, while a revert in a later month counts as a change in that month. A changed or new line keeps an old year only when `git blame -w -C` over that month traces it to a
  line that disappeared in the same month, as in moves, splits, renames and the ignored reformatting commits;
  a copy of code that is still there counts as new. A year's code therefore never grows after the year ends, and `analyze.py`
  stops with an error if it would. Blaming each snapshot on its own does not hold that: what `-C` recognises
  as moved depends on the surrounding lines, so an old line can change year when its neighbours are edited.
- **History before 2013.** civicrm-core's history starts on 2013-02-28 with "Import from SVN". `analyze.py`
  fetches the archive [civicrm/civicrm-svn](https://github.com/civicrm/civicrm-svn) and grafts its `master`
  tip under the import commit (`git replace --graft`). That tip differs from the import by 57 lines.
- **Mechanical commits** listed in [`ignore-revs.txt`](ignore-revs.txt) are skipped via
  `--ignore-revs-file`: mass reformatting (including the April 2012 CRM-9979 runs and their reverts), short
  array syntax, licence, copyright and version headers, type hints and phpcs clean-ups.
- **Snapshots** are the last first-parent commit before the first of each month. Each month blames only the
  files that changed since the previous snapshot, and only over that month (`git blame <previous>..<snapshot>`),
  so a run costs about as much as the history it covers once. A line from before the month points to the
  commit where blame stopped: the previous snapshot, or for branches merged that month the commit they started
  from, whose line is mapped to the previous snapshot through `git diff -w`. Survival relates a cohort's lines at each snapshot to its size on the January 1st after
  its year, which holds everything that reached `master` during that year; a changed line counts as gone.
- **Scope** is code only: `*.php`, `*.tpl`, `*.js`, `*.ts`, `*.html`, `*.css`, `*.scss`. Excluded are
  data and generated code (`sql/`, message templates in `xml/templates/` and their per-version copies in
  `CRM/Upgrade/*.msg_template/`, `DAO/` classes, `*.civix.php`,
  `CRM/Core/I18n/SchemaStructure*.php`, JSON, minified files) and the bundled
  code listed below. Files with third-party licence headers that remain make up about 0.2 % of today's lines.

## Excluded bundled code

Third-party libraries and CMS modules that were once checked in. Lines count the analysed file types in
the largest January 1st snapshot; for comparison, CiviCRM's own code had 280,675 lines on 2009-01-01.

| Path | Contents | In the repository | Lines (snapshot) |
|---|---|---|---|
| `packages/` | Third-party libraries: Dojo, FCKeditor, TinyMCE, PEAR modules (DB, HTML, Auth, Mail, …), PHPIDS, dompdf, ezc, Smarty, SimpleTest, Selenium | 2005 – Feb 2013, then its own repository | 541,063 (2009) |
| `packages.orig/` | Unpatched upstream copies of libraries in `packages/` | 2006 – Jan 2013 | 33,801 (2012) |
| `PEAR/` | PEAR libraries, superseded by `packages.orig/` | 2004 – 2006 | 9,711 (2006) |
| `js/calendar*.js`, `js/lang/calendar-*.js` | jscalendar date picker with its translations | 2005 – 2009 | 6,262 (2008) |
| `extern/contactserialize.php` | SugarCRM serializer under the SugarCRM Public License | 2005 – 2007 | 2,377 (2006) |
| `tools/extensions/*/packages/` | Google Checkout SDK inside a sample payment extension | until 2015 | 2,261 (2015) |
| `mockups/` | Design mockups, partly saved web pages with copies of jQuery plugins | 2008 – 2012 | 13,081 (2011) |
| `drupal/`, `joomla/`, `WordPress/`, `standalone/`, `mambo/`, `modules/` | CMS integration modules, in their own repositories since 2013 | 2004 – 2013 | 3,075 (`joomla/`, 2013) |
| `l10n/` | Translations | 2005 – 2009 | no code files |

## Limitations

- Code imported from other repositories counts with its import date because its earlier history is not
  linked: APIv4 (2019), civicrm-setup (2020), Flexmailer (2020), RiverLea (2022) and the schema conversion
  to `*.entityType.php` (2024). These areas look younger than they are.
- `ignore-revs.txt` covers commits with 800 or more changed lines that are mechanical by subject or by
  diff (85 % or more of the changed lines are licence, copyright or version headers), not every small one.
  Lines such a commit adds rather than rewrites still count for it.

## Files

| Path | Purpose |
|---|---|
| `analyze.py` | Fetch, graft SVN history, blame each month in parallel, follow lines from snapshot to snapshot, write `docs/data.json` |
| `ignore-revs.txt` | Mechanical commits skipped by blame, each with date and subject |
| `docs/index.html` | The page; no build step, no dependencies besides Google Fonts |
| `docs/data.json` | Generated data: per file and per snapshot, lines per year from 2004 |

## License

[AGPL-3.0](LICENSE)
