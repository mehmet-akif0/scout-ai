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

Data persists across browser refreshes and server restarts. To back up, stop the app and copy the `data/` directory. To restore, stop the app and replace it with the backup. CSV export is available for portability; CSV import is not included. Formula-like CSV cells are prefixed with an apostrophe to prevent spreadsheet execution.

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
