#!/usr/bin/env bash
# Installer for macOS and Linux. Windows users: run setup.ps1 instead.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/leetcode_save.py"

say() { printf '%s\n' "$1"; }
rule() { printf '%s\n' "------------------------------------------------------------"; }

say ""
say "Installing leetcode-save"
rule
say ""

# ---------------------------------------------------------------- requirements
say "Step 1 of 4: checking what you already have"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    say "  Python 3.8+   MISSING"
    say ""
    say "This tool is written in Python, so you need it installed first."
    say "  macOS:  brew install python3"
    say "  Linux:  sudo apt install python3 python3-pip"
    exit 1
fi
say "  Python        $("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if ! command -v git >/dev/null 2>&1; then
    say "  git           MISSING"
    say ""
    say "Your solutions are stored in a git repo, so git is required."
    say "  macOS:  xcode-select --install"
    say "  Linux:  sudo apt install git"
    exit 1
fi
say "  git           $(git --version | awk '{print $3}')"

if command -v gh >/dev/null 2>&1; then
    say "  GitHub CLI    $(gh --version | head -1 | awk '{print $3}')"
else
    say "  GitHub CLI    not installed (optional)"
    say "                Without it, you'll be asked to point at a repo you"
    say "                cloned yourself instead of it making one for you."
fi
say ""

# ------------------------------------------------------------------- packages
say "Step 2 of 4: installing the Python packages it needs"
say "  (requests, python-dotenv, html2text)"

if ! "$PYTHON" -m pip install --quiet --user -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null; then
    # Some distros ship an "externally managed" Python that refuses --user.
    if ! "$PYTHON" -m pip install --quiet --user --break-system-packages \
        -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null; then
        say "  FAILED to install packages."
        say ""
        say "Try running this yourself to see the error:"
        say "  $PYTHON -m pip install --user -r '$SCRIPT_DIR/requirements.txt'"
        exit 1
    fi
fi
say "  done"
say ""

# -------------------------------------------------------------------- command
say "Step 3 of 4: creating the 'leetcode-save' command"

chmod +x "$SCRIPT"

BIN_DIR=""
for candidate in "$HOME/.local/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    if [ -d "$candidate" ] && [ -w "$candidate" ]; then
        BIN_DIR="$candidate"
        break
    fi
done
if [ -z "$BIN_DIR" ]; then
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
fi

LINK="$BIN_DIR/leetcode-save"
ln -sf "$SCRIPT" "$LINK"
say "  installed at $LINK"
say ""

# --------------------------------------------------------------------- verify
say "Step 4 of 4: checking that it runs"

if "$PYTHON" "$SCRIPT" --help >/dev/null 2>&1; then
    say "  works"
else
    say "  The command was installed but failed to start."
    say "  Run this to see why:  $PYTHON '$SCRIPT' --help"
    exit 1
fi
say ""

# ----------------------------------------------------------------- PATH notes
ON_PATH=no
case ":$PATH:" in
    *":$BIN_DIR:"*) ON_PATH=yes ;;
esac

if [ "$ON_PATH" = no ]; then
    case "${SHELL##*/}" in
        zsh)  PROFILE="$HOME/.zshrc" ;;
        bash) PROFILE="$HOME/.bashrc" ;;
        *)    PROFILE="$HOME/.profile" ;;
    esac
    rule
    say "One extra step: your shell can't see $BIN_DIR yet."
    say ""
    say "Copy and run this line:"
    say ""
    say "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $PROFILE && source $PROFILE"
    say ""
fi

rule
say "Setup finished. Two things left to do."
say ""
say "1. Log in to LeetCode:"
say ""
say "     leetcode-save --login"
say ""
say "   It prints instructions and waits. You'll copy one thing"
say "   out of Chrome and paste it in. Takes about 30 seconds."
say ""
say "2. From then on, whenever you solve a problem:"
say ""
say "     leetcode-save"
say ""
say "   That saves it to GitHub. Safe to run any time -- it only"
say "   saves what's new and never touches what's already saved."
say ""
rule

if [ "$ON_PATH" = yes ]; then
    say ""
    say "Note: if you get 'command not found', run 'rehash' or open a"
    say "new terminal. Shells cache the commands they know about at"
    say "startup, so one added just now may be invisible until then."
fi
