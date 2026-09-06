#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/leetcode_save.py"

echo "==> Installing Python dependencies..."
python3 -m pip install --quiet --user -r "$SCRIPT_DIR/requirements.txt"

echo "==> Making script executable..."
chmod +x "$SCRIPT"

# Pick an install dir we can actually write to. /usr/local/bin does not exist by
# default on Apple Silicon, so prefer ~/.local/bin and fall back from there.
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
echo "==> Linking $LINK ..."
ln -sf "$SCRIPT" "$LINK"

echo ""
echo "Installed to $BIN_DIR"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "Run: leetcode-save --help"
        ;;
    *)
        echo ""
        echo "WARNING: $BIN_DIR is not on your PATH. Add it:"
        echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
        ;;
esac

echo ""
echo "Next steps:"
echo "  1. Create a repo for your solutions and clone it:"
echo "       gh repo create leetcode-solutions --public --clone"
echo "  2. Copy the config template:"
echo "       cp '$SCRIPT_DIR/.env.example' ~/.leetcode-save.env && chmod 600 ~/.leetcode-save.env"
echo "  3. Add your LeetCode cookies and repo path to ~/.leetcode-save.env"
echo "  4. Solve something, then run:  leetcode-save --latest"
