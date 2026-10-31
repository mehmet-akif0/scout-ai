# Open ScoutAI on Windows

Use Windows 10/11 and **Python 3.12, 64-bit**. Git, Node.js, administrator access, and an API key are not required. Native Windows execution has not been tested in this Linux workspace.

1. Install Python 3.12 (64-bit) from [python.org](https://www.python.org/downloads/windows/). In the installer enable **Add python.exe to PATH** and the Python launcher. If Python is already installed, setup will check its version.
2. Open [ScoutAI on GitHub](https://github.com/mehmet-akif0/scout-ai). Choose **Code → Download ZIP**, then **Extract All**. Open the extracted folder containing `setup_windows.cmd`. Do not run from inside the ZIP. A folder such as `Documents\ScoutAI` is suitable.
3. Double-click **setup_windows.cmd** once. It creates the virtual environment and downloads the pinned Python packages. Internet access is needed for this installation, not for manual app use. Keep the window open until it says **Setup complete**. Setup never removes your data or replaces an existing local settings file.
4. Double-click **start_windows.cmd**. Keep its console window open. A browser opens when the server is ready; if not, visit **http://127.0.0.1:8501** on this same Windows computer. The app listens only on localhost, not your home network or the public internet.
5. Use **Startup catalog**, **Scouting Profiles**, and **Metrics & Analytics** without an API key. No AI requests run automatically. Stop ScoutAI with **Ctrl+C** in the console. Next time, only run `start_windows.cmd` again.

## Optional private API configuration

Setup copies `scoutai.local.example.toml` to **scoutai.local.toml** only if the latter does not exist. The example contains empty values only. Leave them empty for manual use.

If you later choose to enable research, edit **scoutai.local.toml** in Notepad and fill only the `SCOUTAI_AI_API_KEY` value between its existing quotes. Save, close ScoutAI, and start it again. Do not put a key in a command, screenshot, CSV, source code, chat, or the example file. This local file is excluded from Git; GitHub Download ZIP does not include it. Never distribute a ZIP of your entire working folder after adding a real key. API calls can cost money and still require explicit actions in the app. Local OpenAI connectivity has not been tested here.

Nonempty operating-system environment variables take precedence over the local file. Blank settings do not enable research. The database path can remain blank: the default is **data\scoutai.db**. If you customize it, make sure the file you restore goes to that configured path.

## Bring your existing cloud records

**Downloading the code from GitHub does not download SQLite records.** Start with a separate backup; keep the original database until you have checked the restored app.

1. In the environment that contains your current records, create a consistent SQLite-only export from the project folder:

   ```text
   .venv/bin/python backup_database.py
   ```

   On an existing Windows installation the equivalent is:

   ```text
   .venv\Scripts\python.exe backup_database.py
   ```

   This writes a new timestamped **data/exports/scoutai-transfer-....db** file and checks its integrity. The SQLite backup API includes committed records in a WAL journal consistently, even if the source connection is still open. It never overwrites an earlier export or changes the source. Prefer stopping the app/worker first so no newer edits are made after the snapshot.
2. Download **only that transfer `.db` file** from the source environment's file view or the prepared file link in chat. This contains your private company research: transfer/store it securely and keep it out of Git. It does not package `.venv`, local settings, environment variables, API credentials, diagnostic files or screenshot folders. Do not copy an actively written `scoutai.db` alone using the file manager; use the export helper so WAL data is not lost.
3. Complete Windows setup, but **close ScoutAI before restoring**. If you already have a Windows `data\scoutai.db`, move it to a safe backup location first; do not overwrite your only copy.
4. Create the **data** folder inside the extracted ScoutAI folder if needed. Copy the downloaded transfer file into it and rename the copy to **scoutai.db**. If Windows hides extensions, turn on **View → Show → File name extensions** to avoid `scoutai.db.db`.
5. Run **start_windows.cmd** and check your company, profiles, lists, analyses and metrics. Keep both source and transfer backups until satisfied. SQLite includes these records together; a company CSV alone does not carry profiles, analyses, queue state or metric history.

Completed/failed research jobs remain history in the copied database. Pending jobs do not run on startup. An interrupted Running job is marked retryable Failed by the existing local recovery logic; no research resumes automatically.

## If it does not open

- **Python not found / wrong version:** install the 64-bit Python 3.12 version, close/reopen setup, and retry.
- **Package download error:** check the installation internet connection and rerun setup. Do not disable TLS verification.
- **Incompatible `.venv`:** rename only `.venv`, then rerun setup. Never copy the managed Linux environment's `.venv` to Windows; never remove `data` to fix Python.
- **Port already in use:** ScoutAI may already be open. Visit the local address, or stop the old console before starting a new one.
- **Local settings error:** restore the blank example syntax. Settings use TOML strings; the app never prints the secret value in its configuration errors.
- **Windows security prompt:** the app needs no public network access. Keep localhost binding; do not open firewall ports or deploy it publicly.

The `.cmd` scripts and Windows `msvcrt` locking branch are prepared but **not executed on a real Windows machine**. Linux tests check configuration loading, loopback launch, database transfer and mocked Windows lock behavior. No claim of a native Windows smoke test is made.
