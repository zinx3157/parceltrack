#!/usr/bin/env bash
# Push ParcelDesk to your GitHub account.
#
#   bash deploy/push-to-github.sh        (from the parceltrack folder)
#   bash push-to-github.sh               (if you copied it next to run.py)
#
# Written for macOS's bash, so the prompts work even when your shell is zsh
# (zsh's `read -p` means something else entirely — that is the trap this avoids).
set -euo pipefail

# Work out which repository the user means: the folder they are standing in if it is a
# checkout, otherwise the nearest parent of this script that is one.
REPO_DIR=""
if [ -d "$PWD/.git" ]; then
  REPO_DIR="$PWD"
else
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [ "$d" != "/" ]; do
    if [ -d "$d/.git" ]; then REPO_DIR="$d"; break; fi
    d="$(dirname "$d")"
  done
fi

if [ -z "$REPO_DIR" ]; then
  echo "!! No git repository found."
  echo "   cd into the parceltrack folder (the one containing run.py) and run this again."
  exit 1
fi
cd "$REPO_DIR"
echo "Repository: $REPO_DIR"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "!! git is not installed. On macOS run:  xcode-select --install"
  exit 1
fi

echo "ParcelDesk -> GitHub"
echo "--------------------"
echo "First create an EMPTY repository on GitHub — no README, no .gitignore, no licence:"
echo "   https://github.com/new"
echo
read -r -p "Your GitHub username: " GHUSER
read -r -p "Repository name [parceltrack]: " GHREPO
GHREPO="${GHREPO:-parceltrack}"

if [ -z "$GHUSER" ]; then
  echo "!! Username cannot be empty."
  exit 1
fi

REMOTE="https://github.com/${GHUSER}/${GHREPO}.git"
echo
echo "Remote: $REMOTE"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
  echo "(updated the existing 'origin' remote)"
else
  git remote add origin "$REMOTE"
  echo "(added the 'origin' remote)"
fi

git branch -M main

echo
echo "Pushing to GitHub..."
echo "When asked for a password, paste a Personal Access Token (NOT your account password):"
echo "   https://github.com/settings/tokens  ->  Generate new token (classic)  ->  tick 'repo'"
echo
if git push -u origin main; then
  echo
  echo "Done — your code is live at https://github.com/${GHUSER}/${GHREPO}"
  echo "To update your server later:  git pull   (then restart ParcelDesk)"
else
  echo
  echo "!! The push failed. The usual causes:"
  echo "   1. The repository does not exist yet      ->  https://github.com/new"
  echo "   2. Username or repository name is wrong   ->  run the script again"
  echo "   3. The password was your GitHub password  ->  use a Personal Access Token"
  exit 1
fi
