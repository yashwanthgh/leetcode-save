#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/leetcode_save.py"
LINK="/usr/local/bin/leetcode-save"

echo "==> Installing dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet

echo "==> Making script executable..."
chmod +x "$SCRIPT"

echo "==> Creating symlink at $LINK ..."
if [ -L "$LINK" ]; then
    rm "$LINK"
fi
ln -s "$SCRIPT" "$LINK"

echo ""
echo "✓ Installed! Run: leetcode-save --help"
echo ""
echo "Next steps:"
echo "  1. Create a GitHub repo for your solutions (e.g. leetcode-solutions)"
echo "  2. Clone it:  git clone https://github.com/YOUR_USERNAME/leetcode-solutions ~/leetcode-solutions"
echo "  3. Copy .env.example:  cp '$SCRIPT_DIR/.env.example' ~/.leetcode-save.env"
echo "  4. Edit ~/.leetcode-save.env with your LeetCode cookies + repo path"
echo "  5. Solve a problem on LeetCode, then run:  leetcode-save two-sum"
