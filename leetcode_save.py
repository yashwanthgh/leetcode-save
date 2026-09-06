#!/usr/bin/env python3
"""leetcode-save: fetch a LeetCode problem + your accepted solution and commit to GitHub."""

import os
import re
import sys
import json
import warnings
import subprocess
import argparse
from pathlib import Path

# macOS ships a system Python linked against LibreSSL, which makes urllib3 emit a
# NotOpenSSLWarning on every run. It is harmless here and only confuses users.
warnings.filterwarnings("ignore", message=r".*OpenSSL.*")

try:
    import requests
    from dotenv import load_dotenv
    import html2text
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install requests python-dotenv html2text")
    sys.exit(1)

GRAPHQL_URL = "https://leetcode.com/graphql"

BLOCK = ("/*", "*/")
TRIPLE = ('"""', '"""')

# lang key -> (file extension, comment delimiters)
LANG_MAP = {
    "java": ("java", BLOCK),
    "python": ("py", TRIPLE),
    "python3": ("py", TRIPLE),
    "cpp": ("cpp", BLOCK),
    "c": ("c", BLOCK),
    "javascript": ("js", BLOCK),
    "typescript": ("ts", BLOCK),
    "go": ("go", BLOCK),
    "rust": ("rs", BLOCK),
    "kotlin": ("kt", BLOCK),
    "swift": ("swift", BLOCK),
}


CONFIG_PATH = Path.home() / ".leetcode-save.env"


def write_config_values(updates):
    """Update keys in the config file, leaving every other line untouched."""
    lines = CONFIG_PATH.read_text().splitlines() if CONFIG_PATH.exists() else []
    remaining = dict(updates)

    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={value}")

    CONFIG_PATH.write_text("\n".join(out) + "\n")
    CONFIG_PATH.chmod(0o600)


def whoami(session, csrf):
    """Confirm a cookie pair is valid and return the account it belongs to."""
    headers = make_headers({"session": session, "csrf": csrf})
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": "query { userStatus { isSignedIn username } }"},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    status = ((resp.json().get("data") or {}).get("userStatus")) or {}
    return status.get("username") if status.get("isSignedIn") else None


def sync_cookies():
    """Pull LeetCode cookies out of a 'Copy as cURL' blob sitting on the clipboard."""
    clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

    if not clip.strip():
        print("Clipboard is empty. See --help for the copy step.")
        sys.exit(1)

    session = re.search(r"LEETCODE_SESSION=([^;'\"\s]+)", clip)
    csrf = re.search(r"csrftoken=([^;'\"\s]+)", clip)

    if not session or not csrf:
        print("Couldn't find LeetCode cookies on the clipboard.")
        print("")
        print("Do this in Chrome:")
        print("  1. Open leetcode.com (logged in)")
        print("  2. DevTools -> Network tab, then reload the page")
        print("  3. Click the top request, right-click it")
        print("  4. Copy -> Copy as cURL")
        print("  5. Re-run: leetcode-save --sync-cookies")
        sys.exit(1)

    session, csrf = session.group(1), csrf.group(1)

    print("Found both cookies. Checking them with LeetCode...")
    user = whoami(session, csrf)
    if not user:
        print("LeetCode rejected those cookies — are you logged in in that browser?")
        sys.exit(1)

    write_config_values(
        {
            "LEETCODE_SESSION": session,
            "LEETCODE_CSRF": csrf,
            "LEETCODE_USERNAME": user,
        }
    )
    print(f"Signed in as '{user}'. Saved to {CONFIG_PATH}")
    print("Ready — try: leetcode-save --latest")


def load_config():
    config_path = CONFIG_PATH
    if config_path.exists():
        load_dotenv(config_path)
    else:
        load_dotenv()

    missing = []
    session = os.getenv("LEETCODE_SESSION")
    csrf = os.getenv("LEETCODE_CSRF")
    repo_path = os.getenv("GITHUB_REPO_PATH")
    username = os.getenv("LEETCODE_USERNAME", "")

    if not session:
        missing.append("LEETCODE_SESSION")
    if not csrf:
        missing.append("LEETCODE_CSRF")
    if not repo_path:
        missing.append("GITHUB_REPO_PATH")

    if missing:
        print("Missing required config in ~/.leetcode-save.env:")
        for key in missing:
            print(f"  {key}=...")
        if "LEETCODE_SESSION" in missing or "LEETCODE_CSRF" in missing:
            print("\nFor the cookies, run:  leetcode-save --sync-cookies")
        sys.exit(1)

    repo = Path(repo_path).expanduser()
    if not repo.exists():
        print(f"Repo path not found: {repo}")
        print("Clone your GitHub repo there first.")
        sys.exit(1)

    return {
        "session": session,
        "csrf": csrf,
        "username": username,
        "repo_path": repo,
    }


def make_headers(config):
    return {
        "Cookie": f"LEETCODE_SESSION={config['session']}; csrftoken={config['csrf']}",
        "x-csrftoken": config["csrf"],
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "User-Agent": "Mozilla/5.0",
    }


def auth_failed():
    print("LeetCode rejected your session cookie — they expire periodically.")
    print("To refresh: on leetcode.com open DevTools -> Network, reload the page,")
    print("right-click the top request -> Copy -> Copy as cURL, then run:")
    print("  leetcode-save --sync-cookies")
    sys.exit(1)


def fetch_problem(slug, headers):
    query = """
    query questionData($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionFrontendId
        title
        titleSlug
        content
        difficulty
        topicTags { name }
        hints
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": {"titleSlug": slug}},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        print(f"LeetCode API error: {data['errors'][0]['message']}")
        sys.exit(1)

    problem = data["data"]["question"]
    if not problem:
        print(f"Problem not found: '{slug}'")
        print("Use the URL slug, e.g. 'two-sum' from leetcode.com/problems/two-sum/")
        sys.exit(1)

    return problem


def fetch_submission_id(slug, lang_key, headers):
    """Return the most recent accepted submission ID for the given problem and language."""
    query = """
    query submissionList($questionSlug: String!, $offset: Int!, $limit: Int!) {
      submissionList(questionSlug: $questionSlug, offset: $offset, limit: $limit) {
        submissions {
          id
          statusDisplay
          lang
        }
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={
            "query": query,
            "variables": {"questionSlug": slug, "offset": 0, "limit": 20},
        },
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    listing = (data.get("data") or {}).get("submissionList") or {}
    submissions = listing.get("submissions")
    # LeetCode answers HTTP 200 with a null payload when the session cookie is
    # rejected. An authenticated account with no submissions yields [] instead,
    # so null specifically means "not authenticated".
    if submissions is None:
        auth_failed()

    for sub in submissions:
        if sub["statusDisplay"] == "Accepted" and sub["lang"].lower() == lang_key.lower():
            return sub["id"]

    return None


def fetch_submission_code(submission_id, headers):
    query = """
    query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId: $submissionId) {
        code
        lang { name }
        runtimeDisplay
        memoryDisplay
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={
            "query": query,
            "variables": {"submissionId": int(submission_id)},
        },
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    details = (data.get("data") or {}).get("submissionDetails")
    if not details:
        print(f"Could not fetch code for submission {submission_id}.")
        sys.exit(1)
    return details


def fetch_recent_accepted(lang_key, headers, scan=25):
    """Most recent accepted submission in a language, across all problems.

    Uses the authenticated submissionList rather than recentAcSubmissionList,
    which returns an empty array even for accounts with solved problems.
    """
    query = """
    query submissionList($offset: Int!, $limit: Int!) {
      submissionList(offset: $offset, limit: $limit) {
        submissions {
          id
          title
          titleSlug
          statusDisplay
          lang
        }
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": {"offset": 0, "limit": scan}},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    listing = (data.get("data") or {}).get("submissionList") or {}
    submissions = listing.get("submissions")
    if submissions is None:
        auth_failed()

    for sub in submissions:
        if sub["statusDisplay"] == "Accepted" and sub["lang"].lower() == lang_key.lower():
            return sub

    return None


def html_to_plaintext(html_content):
    """LeetCode ships problem statements as HTML; flatten to text for a comment block."""
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_links = False
    h.protect_links = True
    # Emphasis markers render as literal '**' noise inside a code comment.
    h.ignore_emphasis = True

    text = h.handle(html_content)
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_file_content(problem, submission_details, delims):
    """Solution code first, then the problem description in a trailing comment block."""
    open_c, close_c = delims
    tags = ", ".join(t["name"] for t in (problem.get("topicTags") or []))
    runtime = (submission_details or {}).get("runtimeDisplay", "N/A")
    memory = (submission_details or {}).get("memoryDisplay", "N/A")

    description = html_to_plaintext(problem.get("content") or "")

    hints = problem.get("hints") or []
    if hints:
        description += "\n\nHints:\n"
        for i, hint in enumerate(hints, 1):
            description += f"  {i}. {html_to_plaintext(hint)}\n"

    # A literal close delimiter inside the description would terminate the block early.
    description = description.replace(close_c, close_c[0] + " " + close_c[1:])

    url = f"https://leetcode.com/problems/{problem['titleSlug']}/"

    return f"""{submission_details['code'].rstrip()}

{open_c}
{problem['questionFrontendId']}. {problem['title']}
{url}

Difficulty : {problem['difficulty']}
Topics     : {tags}
Runtime    : {runtime}
Memory     : {memory}

{'-' * 60}

{description.strip()}
{close_c}
"""


def save_to_repo(problem, submission_details, repo_path, lang_key):
    num = str(problem["questionFrontendId"]).zfill(4)
    ext, delims = LANG_MAP.get(lang_key.lower(), ("txt", BLOCK))
    filename = f"{num}-{problem['titleSlug']}.{ext}"

    (repo_path / filename).write_text(
        build_file_content(problem, submission_details, delims), encoding="utf-8"
    )

    return filename


def git_commit_push(repo_path, filename, problem_title, no_push):
    def run(cmd, check=True):
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"git error: {result.stderr.strip()}")
            sys.exit(1)
        return result.stdout.strip()

    run(["git", "add", filename])

    status = run(["git", "status", "--porcelain"])
    if not status:
        print("Nothing to commit — solution already saved.")
        return

    run(["git", "commit", "-m", f"solve: {problem_title}"])

    if no_push:
        print("Committed locally (--no-push was set, skipping push).")
    else:
        run(["git", "push"])
        print("Pushed to GitHub.")


def main():
    parser = argparse.ArgumentParser(
        description="Save a LeetCode problem + your solution to GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  leetcode-save --sync-cookies       # grab your LeetCode cookies from the clipboard
  leetcode-save two-sum              # save 'two-sum' Java solution
  leetcode-save two-sum --lang cpp   # save C++ solution
  leetcode-save --latest             # save most recently accepted problem
  leetcode-save two-sum --no-push    # save locally without pushing

First-time setup:
  In Chrome on leetcode.com (logged in): DevTools -> Network, reload,
  right-click the top request -> Copy -> Copy as cURL.
  Then run: leetcode-save --sync-cookies
        """,
    )
    parser.add_argument("slug", nargs="?", help="Problem slug, e.g. two-sum")
    parser.add_argument(
        "--sync-cookies",
        action="store_true",
        help="Read your LeetCode cookies from a 'Copy as cURL' blob on the clipboard",
    )
    parser.add_argument(
        "--latest", action="store_true", help="Use your most recent accepted submission"
    )
    parser.add_argument("--lang", default="java", help="Language key (default: java)")
    parser.add_argument(
        "--no-push", action="store_true", help="Commit locally but don't push"
    )
    args = parser.parse_args()

    if args.sync_cookies:
        sync_cookies()
        return

    if not args.slug and not args.latest:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    headers = make_headers(config)

    lang_key = args.lang.lower()

    if args.latest:
        print(f"Finding your most recent accepted {lang_key} submission...")
        recent = fetch_recent_accepted(lang_key, headers)
        if not recent:
            print(f"No accepted {lang_key} submission in your recent history.")
            print(f"Tip: pass a slug directly, or try --lang <other language>.")
            sys.exit(1)
        slug, sub_id = recent["titleSlug"], recent["id"]
        print(f"  → {recent['title']}")
    else:
        slug, sub_id = args.slug, None

    print(f"Fetching problem: {slug}")
    problem = fetch_problem(slug, headers)
    print(f"  → #{problem['questionFrontendId']} {problem['title']} ({problem['difficulty']})")

    if sub_id is None:
        print(f"Looking for your accepted {lang_key} submission...")
        sub_id = fetch_submission_id(slug, lang_key, headers)
        if not sub_id:
            print(f"No accepted {lang_key} submission found for '{slug}'.")
            print("Tip: make sure you've submitted and it passed on leetcode.com")
            sys.exit(1)

    submission = fetch_submission_code(sub_id, headers)
    print(
        f"  → Runtime: {submission.get('runtimeDisplay', 'N/A')}"
        f"  Memory: {submission.get('memoryDisplay', 'N/A')}"
    )

    filename = save_to_repo(problem, submission, config["repo_path"], lang_key)
    print(f"Saved: {filename}")

    git_commit_push(config["repo_path"], filename, problem["title"], args.no_push)
    print(f"\nDone! ✓  #{problem['questionFrontendId']} {problem['title']}")


if __name__ == "__main__":
    main()
