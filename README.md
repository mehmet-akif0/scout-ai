# ScoutAI

A personal startup scouting application built with Python, Streamlit, and SQLite. The interface and repository documentation are in English.

## Requirements

- Python 3.12 (tested); Python 3.10+ supported by Streamlit.
- Streamlit **1.50.0**, pinned in `requirements.txt`.
- SQLite is included with Python; no separate database server is required.
- No external API, AI connection, credentials, or Node.js installation required.

## Install and run

From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

On Windows, activate using `.venv\Scripts\activate` instead.

Open **http://127.0.0.1:8501** in your browser. Stop the server with Ctrl+C. Run the same Streamlit command to open it again; existing records remain saved.

## How to use

1. Open **Add startup**, enter the company name, and fill in any research details. Click **Add startup**.
2. In **Browse & edit**, search by company name or filter by sector, investment stage, and status in the sidebar.
3. Select a startup, edit its details, and click **Save changes**.
4. To remove it, expand **Delete startup**, check the confirmation box, then click **Delete startup**.
5. Click **Export filtered list as CSV** to download the current results. Clear filters to export all records.

Fields: company name, website, founders, sector, country, investment stage, short description, source links (one URL per line), personal notes, and status. Statuses are **New**, **Researching**, **Shortlisted**, and **Passed**. Only company name is required; stage defaults to Unknown, status to New.

The workspace starts empty. No demo records or fabricated startup data are inserted. AI analysis and automatic web discovery are outside this first version.

## Local data and privacy

The default database is `data/scoutai.db`, separate from the previous Node.js prototype's database. The earlier database is left untouched; automatic migration is not included. To use another path, set `SCOUTAI_DB_PATH` before starting the app.

Data persists across browser refreshes and server restarts. To back up, stop the app and copy the `data/` directory. To restore, stop the app and replace it with the backup. CSV export is available for portability; Bulk Import supports mapped CSV and website URL intake (see below). Formula-like CSV cells are prefixed with an apostrophe to prevent spreadsheet execution.

`.gitignore` excludes databases, virtual environments, `.env` files and Streamlit secrets. Never commit real credentials or personal research data. This is a single-user local application without login or access control. Keep it bound to localhost; add authentication and HTTPS before exposing it to other users.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Tests use temporary databases and Streamlit's AppTest to check creation, editing, deletion, validation, search and filters, CSV export, and persistence. No real workspace records are changed.

## Project structure

- `app.py`: English Streamlit interface.
- `storage.py`: SQLite queries, validation, and CSV export.
- `catalog.py`: catalog metadata, sources, claims, versioned analyses, watchlists, and import storage.
- `catalog_ui.py`: catalog/detail reader, local administration, watchlists, and Bulk Import.
- `profiles.py` / `profile_ui.py`: versioned Scouting Profiles and independent manual assessments.
- `requirements.txt`: pinned application dependency.
- `tests/`: database and UI flow tests.

There is no compilation or build step. Streamlit dependencies are installed by pip.

## Scouting Profiles

Open the **Scouting Profiles** tab to create, name, edit, or delete research profiles. Choose an **Active Scouting Profile** in the sidebar; the choice is stored in SQLite and restored in new sessions.

Each profile can specify target sectors, headquarters countries/regions, investment stages, business model (B2B, B2C, B2B2C, or Any), excluded companies, excluded investors, and custom criteria. Headquarters means the company's location, **not founder origin or nationality**. For custom criteria, add rows with a name and a rule. Each criterion is Required or Preferred. Blank values and the Any business model impose no restrictions. No geography, sector, founder background, or investment strategy is preselected.

In **Browse & edit**, select a startup and use **Profile assessment** below its company information. For every configured criterion, choose **Meets**, **Does not meet**, or **Unknown**, and record a rationale, optional source URL, and assessment date. For an exclusion rule, Meets means that the company passes the exclusion rule. These are manual judgments; no web requests or automatic matching are performed. All criteria are saved together for that profile and startup.

The sidebar's **Filter by profile assessment** filters the list using the active profile:

- **Not evaluated**: no assessment for this profile and company.
- **Review needed**: criteria changed after the saved assessment. Historical results are retained and displayed separately; current criteria start at Unknown until reviewed.
- **Does not meet required criteria**: at least one Required criterion is explicitly not met.
- **Needs research**: no Required criterion fails, but at least one is Unknown. Unknown is never counted as failure.
- **Meets required criteria**: all Required criteria are explicitly met. Preferred misses or unknowns do not disqualify the company; check individual results for details.
- **Reviewed (no required criteria)**: a preferred-only profile was assessed; this label does not assert eligibility.
- **No criteria configured**: the profile imposes no restrictions and has nothing to assess.

The list status is specific to the active profile. The original company status (New, Researching, Shortlisted, Passed) remains separate. Company information, including existing personal notes, is shared across profiles; assessment rationales and results are profile-specific. CSV export continues to export company records; assessment history remains in the SQLite database.

### Persistence and upgrades

The application adds `scouting_profiles`, `profile_versions`, `assessments`, and `workspace_settings` tables to the existing SQLite file on first use. It does not replace or rewrite startup rows. Initialization is repeatable. Back up your database before upgrading using the procedure above. Profile deletion removes only that profile and its assessments; startups and other profiles remain. Deleting a startup removes assessments attached to that startup.

Changes to criterion targets, names, priorities, additions, or removals create a new criteria version. Changing only the profile name does not invalidate assessments. Previous versions and their assessments remain available under **Saved assessment history**. Editing an assessment within the same criteria version replaces that version's response; this is not a full audit log of every edit. Company data changes are not automatically assessed against profiles: revisit judgments when new evidence arrives.

Tests cover additive migration with existing records, repeated initialization, profile separation, persistent active selection, deletion boundaries, Required/Preferred/Unknown logic, stale revision rejection, historical criteria snapshots, and Streamlit profile/assessment flows. Existing company CRUD and CSV tests remain in place. No AI, accounts, online research, or public deployment is introduced.


## Catalog and company details

Under **Local administration**, open **Startup catalog** for company cards. Search by company name and combine sector, headquarters country, investment stage, business model, and watchlist filters. Catalog filters are separate from the original sidebar filters used by Browse & edit. Empty company fields display Unknown or Not researched; no demo content is inserted.

Click **Open company details** on a card, or choose a company using the detail selector. Direct links use `?view=reader&startup=123` (replace 123 with the company's stable ID) appended to your app's actual address. The detail selector also works without changing the address. These are app-relative links, not a deployment or a remote preview service.

The sections are Overview, Product, Founders, Business Model, Target Customers, Traction, Funding, Market, Competitors, and Analyses. Original basic company fields remain editable in Browse & edit; catalog-specific business model and research status are editable under Manage company metadata. Original notes and profile assessments remain separate and are not displayed in Reader mode.

### Evidence and structured analyses

1. In company details, expand **Add evidence source** and enter the URL, optional publication date, access date, origin, and provenance note. Unknown publication dates are saved as null, not today's date.
2. Use **Add or edit sourced company information** to attach assertions to a section. Select evidence IDs for each assertion. Basic legacy company fields are explicitly unverified; they are not automatically converted into corroborated claims.
3. Labels are Company claim, Independently corroborated, and Analyst interpretation. Factual claims require supporting sources. Independently corroborated requires at least one source manually classified as Independent **and** a written corroboration basis. The app validates this structure, not the truth of the source or its independence; no website is fetched.
4. In **Write or edit an analysis**, choose New dated analysis or a saved version. Fill in any of the nine structured headings and associate sources/labels with each populated section. A memo needs a title, a date, and at least one populated heading. Empty headings show Not researched.
5. **Save draft** saves only a Draft. To publish, select that saved draft and click **Publish saved draft** outside the form. Save form edits before publishing: publishing uses persisted content.
6. Editing a Published version creates a new Draft within the same analysis series. Editing a Draft updates that draft. Published versions remain immutable. Separate New dated analyses create separate series. Readers see the highest published version in each series, never drafts.

Switch **Workspace view** to **Reader** to check this separation. Local administration remains available to anyone using this single-user app; Reader is a presentation mode, **not authentication**. Publishing here changes only content status inside SQLite; it never deploys anything to the internet.

The analysis headings are Problem and customer need; Product and value proposition; Market opportunity; Competition and differentiation; Go-to-market; Traction and evidence; Team; Strengths; Risks and open questions. General analyses do not modify Scouting Profiles or their assessments.

### Watchlists

Open **Watchlists** to create or rename a list and select its companies. Save an empty company selection to remove all members. Deleting a list requires confirmation and removes only the list membership, never companies. Use Catalog watchlist to browse its cards.

## Bulk Import

Choose **Bulk Import** in Local administration:

- **CSV upload**: upload UTF-8 CSV (a UTF-8 BOM is accepted), then map each app field to a CSV column or leave it unmapped. At least company name or website must be present in each row. A company with only a website uses its normalized host as a placeholder name; this is not a researched legal name.
- **Website URLs**: paste one explicit `https://` or `http://` company URL per line. No scraping, domain enrichment, redirect resolution, AI requests, or inferred company facts occur.
- Review the preview's Add, Skip, and Error actions and reasons before checking the confirmation box. Import valid rows skips duplicates and invalid rows and reports added/skipped/error counts.
- Website identities compare normalized exact hosts, ignoring www, case, paths, and trailing dots. Subdomains are separate; redirects and registrable-domain equivalence are not resolved. Similar names generate a warning but never cause automatic merging.
- Identical name-only mapped rows use a content fingerprint for repeat-import idempotence. Different rows with similar names stay separate; these can be reviewed manually.
- Existing companies are always skipped on a domain match. No existing filled fields are updated or merged. This version deliberately offers add-only intake.
- All added records are **Not researched**, separate from the original New/Researching/Shortlisted/Passed workflow status. Blank investment stage/business model become Unknown. Other nonempty stages, statuses, and business models must match the app's English options.
- Upload at most 5,000 rows per import. Preview performs no writes; commit checks duplicates again under a SQLite write lock.

At the bottom, **Prepare a future research selection** saves stable company IDs in the order selected. This is groundwork for a later research phase only. It creates no AI jobs, calls no APIs, and never changes research status automatically.

### Catalog storage, migration and limits

Catalog startup creates additional tables with `CREATE TABLE IF NOT EXISTS` in a transaction. It leaves existing startup, profile, criteria-version and assessment rows intact. Missing company metadata uses Unknown / Not researched without inventing facts. Back up the SQLite file before upgrading. Company deletion cascades to attached sources, facts, analyses, memberships and research selections; deleting a profile or watchlist never deletes companies.

Catalog CSV export still exports the original company fields only, not analyses, evidence, watchlists, or profile assessments. Use a SQLite backup for a complete copy. Sources are add-only in this iteration; claims can be edited and linked to additional source records. Draft saves replace that draft's content; only published analysis versions are immutable. The catalog currently renders all matching cards without pagination. There are no accounts, permissions, AI, automated research, community ratings, or public deployment in this version.

Tests include the existing profile and startup flows plus catalog migration, claim/source ownership, corroboration requirements, immutable published versions, multiple dated analysis series, hidden drafts, direct company reader links, watchlist deletion boundaries, CSV mapping, import preview/idempotence, and ordered future-research selection. UI checks use Streamlit AppTest; they are not a full browser automation suite.
