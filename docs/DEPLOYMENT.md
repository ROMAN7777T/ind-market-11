# Hosting IndQuant Terminal online (Streamlit Community Cloud)

This is a **Python app**, not a static website: there is no `index.html`, and GitHub Pages or Netlify cannot run it.
The entry point is `app.py`. The steps below use Streamlit Community Cloud (free).

## Before you start: what changes when it's online

- **Password required.** A copy reached over the network will not open until `app_password` is set in the host's Secrets.
  Local use on your own computer needs no password.
- **Broker connections are disabled** on a hosted copy. Connect Kotak only on your own computer.
- **Data may be wiped.** Free hosts reset their disk when the app restarts or redeploys. Paper trades, imported CSVs and
  settings on the hosted copy can disappear. Your own computer remains the place where data is kept.
- **Everything is still paper trading only.** No real orders exist in the code.
- Never upload `.env`, `.streamlit/secrets.toml`, `data/`, `logs/` or `.venv/`. `.gitignore` already excludes them.

## Step 1: Put the project on GitHub (about 10–15 minutes)

1. Create a free account at github.com if you don't have one.
2. Click **New repository**. Name it, for example, `indquant-terminal`. Choose **Private** (recommended), and do **not** add a
   README or .gitignore there.
3. In PowerShell, inside the project folder, run these one at a time (replace `YOUR-NAME`):

```powershell
git init
git add .
git status
```

Check the `git status` list: `.env`, `data/`, `logs/` and `.venv/` must **not** appear. Then:

```powershell
git commit -m "IndQuant Terminal"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/indquant-terminal.git
git push -u origin main
```

GitHub asks you to sign in the first time (a browser window opens).

## Step 2: Deploy on Streamlit Community Cloud (about 5–10 minutes)

1. Go to **share.streamlit.io** and sign in with GitHub. Allow access to the repository (private repositories need this
   permission).
2. Click **Create app** → **Deploy a public app from GitHub**:
   - Repository: `YOUR-NAME/indquant-terminal`
   - Branch: `main`
   - Main file path: `app.py`
3. Open **Advanced settings**:
   - Python version: **3.12**
   - Secrets: paste (with your own long password)

     ```toml
     app_password = "a-long-unique-password-you-use-nowhere-else"
     ```

4. Click **Deploy**. The first build takes a few minutes while it installs `requirements.txt`.
5. Open the app link, enter the password, and press **Generate simulated data** on Overview (the hosted copy starts empty).

To change the password later: App → **Settings → Secrets**, edit, save. The app restarts.

## Updating the hosted copy

After changing code on your computer:

```powershell
git add .
git commit -m "Describe the change"
git push
```

Streamlit Cloud redeploys automatically.

## Troubleshooting

| Problem | Fix |
|---|---|
| "no password is configured, so it will not open" | Add `app_password` under App settings → Secrets. |
| Build fails on a package | Check the build log. The versions in `requirements.txt` are pinned and tested on Python 3.12. |
| Data disappeared | Expected on free hosting after a restart. Keep your real work on the local copy. |
| `git push` asks for a password | Sign in through the browser window, or use GitHub Desktop instead of the command line. |
