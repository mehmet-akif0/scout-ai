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
