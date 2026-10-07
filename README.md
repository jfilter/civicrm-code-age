# civicrm-code-age

How old is the code in [CiviCRM core](https://github.com/civicrm/civicrm-core)? This repo blames every
code line of civicrm-core, including the SVN history back to 2004, and renders the result as a static page:

- the age mix of the codebase on January 1st of every year since 2006 and today,
- survival curves: how long lines written in a given year stay unchanged, with their half-life,
- the lines alive today per year written,
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
./analyze.sh                                   # clones civicrm-core from GitHub, branch master
./analyze.sh ~/src/civicrm-core master         # or reuse a local clone (shared, read-only)
JOBS=4 ./analyze.sh                            # parallelism, default: CPU count
```

Needs `git`, `bash`, `awk` and Python 3.11+. A run blames the branch tip and one snapshot per year
(`FIRST_SNAPSHOT_YEAR`, default 2006) and takes about two and a half hours on 10 cores. It works in a temporary bare clone,
never touches the source clone, and overwrites `docs/data.json`.

## Method

- **Line age** is the author date of the commit that last changed the line (`git blame -w -C`). A 2008 line
  edited by one character in 2023 counts as 2023. Code moved to another file keeps its age when the source
  file changed in the same commit, as in splits and renames; a copy out of an untouched file counts as new.
- **History before 2013.** civicrm-core's history starts on 2013-02-28 with "Import from SVN". `analyze.sh`
  fetches the archive [civicrm/civicrm-svn](https://github.com/civicrm/civicrm-svn) and grafts its `master`
  tip under the import commit (`git replace --graft`). That tip differs from the import by 57 lines.
- **Mechanical commits** listed in [`ignore-revs.txt`](ignore-revs.txt) are skipped via
  `--ignore-revs-file`: mass reformatting (including the April 2012 CRM-9979 runs and their reverts), short
  array syntax, copyright header rewrites and phpcs clean-ups.
- **Snapshots** repeat the blame on the last commit before January 1st of each year. Survival relates a
  cohort's lines at each snapshot to its size on the January 1st after its year; a changed line counts as gone.
- **Scope** is code only: `*.php`, `*.tpl`, `*.js`, `*.ts`, `*.html`, `*.css`, `*.scss`. Excluded are
  data and generated code (`sql/`, `xml/templates/`, `DAO/` classes, `*.civix.php`,
  `CRM/Core/I18n/SchemaStructure*.php`, JSON, minified files) and the bundled
  code listed below. Files with third-party licence headers that remain make up about 0.2 % of today's lines.

## Excluded bundled code

Third-party libraries and CMS modules that were once checked in. Lines count the analysed file types in
the largest January 1st snapshot; for comparison, CiviCRM's own code had 291,723 lines on 2009-01-01.

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

- SVN branch work appears as `svn merge` commits on `master` and counts with the merge date, weeks to
  months after it was written.
- Code imported from other repositories counts with its import date because its earlier history is not
  linked: APIv4 (2019), civicrm-setup (2020), Flexmailer (2020), RiverLea (2022) and the schema conversion
  to `*.entityType.php` (2024). These areas look younger than they are.
- `ignore-revs.txt` covers commits with 800 or more changed lines that are mechanical by subject or by
  diff (85 % or more of the changed lines are licence, copyright or version headers), not every small one.
  Lines such a commit adds rather than rewrites still count for it.

## Files

| Path | Purpose |
|---|---|
| `analyze.sh` | Clone, graft SVN history, blame in parallel, write `docs/data.json` |
| `aggregate.py` | Fold blame output into per-file and per-snapshot line counts per year |
| `ignore-revs.txt` | Mechanical commits skipped by blame, each with date and subject |
| `docs/index.html` | The page; no build step, no dependencies besides Google Fonts |
| `docs/data.json` | Generated data: per file and per snapshot, lines per year from 2004 |

## License

[AGPL-3.0](LICENSE)
