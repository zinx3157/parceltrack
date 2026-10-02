# Putting ParcelDesk on GitHub

The project is already a git repository with one commit — you just need to point it at your
GitHub account and push. About two minutes.

## 1. Create an empty repository on GitHub

Go to **https://github.com/new** and fill in:

- **Repository name:** `parceltrack` (or anything you like)
- **Visibility:** Private is a sensible default for business software; Public if you want to
  share it
- **Do not** tick "Add a README", ".gitignore" or "license" — the project already has them

Press **Create repository**.

## 2. Push from your machine

**Easiest — the helper script** (it handles macOS/zsh quirks and the branch rename):

```bash
cd ~/Downloads/parceltrack
bash deploy/push-to-github.sh
```

It asks for your GitHub username and repo name, points `origin` at the right place, renames the
branch to `main` and pushes — then prints the URL of your new repository.

**Or by hand**, in the folder that contains `run.py`:

```bash
git remote add origin https://github.com/YOUR-USERNAME/parceltrack.git
git branch -M main
git push -u origin main
```

GitHub will ask for a username and password. The password must be a **Personal Access Token**,
not your account password (GitHub removed password authentication):

1. https://github.com/settings/tokens → **Generate new token (classic)**
2. Tick the **repo** scope, set an expiry, generate, and copy the token
3. Paste the token where git asks for the password (`git config --global credential.helper store`
   saves you typing it every time)

Prefer SSH? Add your key at https://github.com/settings/keys, then:

```bash
git remote add origin git@github.com:YOUR-USERNAME/parceltrack.git
git push -u origin main
```

## 3. Working with the repo afterwards

```bash
git status                  # what changed
git add -A && git commit -m "Describe your change"
git push
```

On your server, to update a running installation:

```bash
git pull
# restart the app — new database columns are added automatically on startup
```

## What is intentionally *not* in the repository

`.gitignore` keeps these on your machine, where they belong:

| Excluded | Why |
|---|---|
| `.env` | Your carrier API keys, SMTP password, WhatsApp/Twilio tokens, `SECRET_KEY` |
| `data/` (`*.db`) | Your live parcel database, including client names and addresses |
| `backups/`, `*.xlsx`, `*.csv` | Exports and backups — client data |
| `.venv/`, `__pycache__/` | Rebuilt from `requirements.txt` on any machine |

Before your first push you can confirm nothing sensitive is staged:

```bash
git status --short
git ls-files | grep -E "\.env$|\.db$" || echo "clean — no secrets or data files tracked"
```

## Optional extras once it is on GitHub

- **CI:** `.github/workflows/tests.yml` running `python tests/test_all_features.py` on every push
  proves the app still works on a clean machine.
- **Issue templates / wiki** for your team's own notes.
- **GitHub Desktop** (https://desktop.github.com) if you prefer clicking to typing.
