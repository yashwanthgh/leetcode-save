#!/usr/bin/env python3
"""leetcode-save: fetch a LeetCode problem + your accepted solution and commit to GitHub."""

import os
import re
import sys
import json
import time
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

SLASH = ("block", "/*", "*/")
TRIPLE = ("block", '"""', '"""')
RACKET = ("block", "#|", "|#")
HASH = ("line", "#")
PERCENT = ("line", "%")
DASH = ("line", "--")

# LeetCode's own language identifiers -> (file extension, comment style)
LANG_MAP = {
    "java": ("java", SLASH),
    "python": ("py", TRIPLE),
    "python3": ("py", TRIPLE),
    "cpp": ("cpp", SLASH),
    "c": ("c", SLASH),
    "csharp": ("cs", SLASH),
    "javascript": ("js", SLASH),
    "typescript": ("ts", SLASH),
    "golang": ("go", SLASH),
    "go": ("go", SLASH),
    "rust": ("rs", SLASH),
    "kotlin": ("kt", SLASH),
    "swift": ("swift", SLASH),
    "scala": ("scala", SLASH),
    "php": ("php", SLASH),
    "dart": ("dart", SLASH),
    "ruby": ("rb", HASH),
    "elixir": ("ex", HASH),
    "erlang": ("erl", PERCENT),
    "racket": ("rkt", RACKET),
    "mysql": ("sql", DASH),
    "mssql": ("sql", DASH),
    "oraclesql": ("sql", DASH),
    "postgresql": ("sql", DASH),
    "pythondata": ("py", TRIPLE),
}


def comment_block(text, style):
    """Wrap text in a comment using whichever style the language supports."""
    kind = style[0]
    if kind == "line":
        prefix = style[1]
        return "\n".join(
            f"{prefix} {line}".rstrip() for line in text.splitlines()
        )

    open_c, close_c = style[1], style[2]
    # A literal close delimiter would terminate the block early.
    safe = text.replace(close_c, close_c[0] + " " + close_c[1:])
    return f"{open_c}\n{safe}\n{close_c}"


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


COPY_STEPS = """Do this in Chrome:
  1. Open leetcode.com (logged in)
  2. DevTools -> Network tab, then reload the page
  3. Right-click the top request -> Copy -> Copy as cURL
  4. Run: leetcode-save --sync-cookies   (or paste it straight in)"""


def extract_cookies(raw):
    session = re.search(r"LEETCODE_SESSION=([^;'\"\s]+)", raw)
    csrf = re.search(r"csrftoken=([^;'\"\s]+)", raw)
    if session and csrf:
        return session.group(1), csrf.group(1)
    return None


def sync_cookies():
    """Read LeetCode cookies from piped stdin, the clipboard, or an interactive paste."""
    found = None

    if not sys.stdin.isatty():
        found = extract_cookies(sys.stdin.read())
    else:
        clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        found = extract_cookies(clip)
        if found:
            print("Found cookies on the clipboard.")
        else:
            print("No LeetCode cookies on the clipboard.")
            print("")
            print(COPY_STEPS)
            print("")
            print("Or paste the curl command here, then press Ctrl-D:")
            try:
                found = extract_cookies(sys.stdin.read())
            except KeyboardInterrupt:
                print("")
                sys.exit(1)

    if not found:
        print("Couldn't find LEETCODE_SESSION and csrftoken in that input.")
        print("")
        print(COPY_STEPS)
        sys.exit(1)

    session, csrf = found

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


def build_file_content(problem, submission_details, style):
    """Solution code first, then the problem description in a trailing comment block."""
    tags = ", ".join(t["name"] for t in (problem.get("topicTags") or []))
    runtime = (submission_details or {}).get("runtimeDisplay", "N/A")
    memory = (submission_details or {}).get("memoryDisplay", "N/A")

    description = html_to_plaintext(problem.get("content") or "")

    hints = problem.get("hints") or []
    if hints:
        description += "\n\nHints:\n"
        for i, hint in enumerate(hints, 1):
            description += f"  {i}. {html_to_plaintext(hint)}\n"

    header = "\n".join(
        [
            f"{problem['questionFrontendId']}. {problem['title']}",
            f"https://leetcode.com/problems/{problem['titleSlug']}/",
            "",
            f"Difficulty : {problem['difficulty']}",
            f"Topics     : {tags}",
            f"Runtime    : {runtime}",
            f"Memory     : {memory}",
            "",
            "-" * 60,
            "",
            description.strip(),
        ]
    )

    return f"{submission_details['code'].rstrip()}\n\n{comment_block(header, style)}\n"


def lang_extension(lang_key):
    return LANG_MAP.get(lang_key.lower(), ("txt", SLASH))[0]


def save_to_repo(problem, submission_details, repo_path, lang_key, version=False):
    """Write the solution file.

    With version=False the canonical <num>-<slug>.<ext> is written. With
    version=True an existing file is kept and a new <num>.<n>-<slug>.<ext>
    is added alongside it, unless that exact code is already stored.

    Returns (filename, outcome) where outcome is new / updated / versioned / duplicate.
    """
    num = str(problem["questionFrontendId"]).zfill(4)
    slug = problem["titleSlug"]
    ext, style = LANG_MAP.get(lang_key.lower(), ("txt", SLASH))
    content = build_file_content(problem, submission_details, style)

    base = repo_path / f"{num}-{slug}.{ext}"

    if not base.exists():
        base.write_text(content, encoding="utf-8")
        return base.name, "new"

    if not version:
        base.write_text(content, encoding="utf-8")
        return base.name, "updated"

    # Runtime and memory differ between runs, so compare only the code itself.
    code = submission_details["code"].rstrip()
    for f in sorted(repo_path.glob(f"{num}*-{slug}.{ext}")):
        if f.read_text(encoding="utf-8").startswith(code):
            return f.name, "duplicate"

    n = 1
    while (repo_path / f"{num}.{n}-{slug}.{ext}").exists():
        n += 1
    versioned = repo_path / f"{num}.{n}-{slug}.{ext}"
    versioned.write_text(content, encoding="utf-8")
    return versioned.name, "versioned"


def git(repo_path, *cmd, check=True):
    result = subprocess.run(
        ["git", *cmd], cwd=repo_path, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        print(f"git error: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def git_commit(repo_path, filename, problem_title):
    """Stage and commit one file. Returns False if it produced no change."""
    git(repo_path, "add", "--", filename)
    if not git(repo_path, "status", "--porcelain"):
        return False
    git(repo_path, "commit", "-m", f"solve: {problem_title}")
    return True


SOLUTION_FILE = re.compile(r"^\d+(?:\.\d+)?-(.+)\.([^.]+)$")


def existing_solutions(repo_path):
    """(slug, extension) pairs already saved, read straight off the filenames."""
    found = set()
    for f in repo_path.iterdir():
        m = SOLUTION_FILE.match(f.name)
        if m:
            found.add((m.group(1), m.group(2)))
    return found


def iter_submissions(headers, page=20, max_pages=50):
    """Walk your submission history, newest first."""
    query = """
    query submissionList($offset: Int!, $limit: Int!) {
      submissionList(offset: $offset, limit: $limit) {
        submissions { id title titleSlug statusDisplay lang }
      }
    }
    """
    offset = 0
    for _ in range(max_pages):
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": {"offset": offset, "limit": page}},
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        listing = ((resp.json().get("data") or {}).get("submissionList")) or {}
        batch = listing.get("submissions")

        if batch is None:
            auth_failed()
        if not batch:
            return

        for sub in batch:
            yield sub

        if len(batch) < page:
            return
        offset += page
        time.sleep(0.3)


def sync_all(config, headers, no_push, lang_filter=None):
    """Save every accepted solution that isn't in the repo yet."""
    repo = config["repo_path"]
    have = existing_solutions(repo)
    print(f"Repo has {len(have)} solution(s) saved. Scanning your history...")

    seen = set()
    saved, skipped, failed = [], 0, []

    for sub in iter_submissions(headers):
        if sub["statusDisplay"] != "Accepted":
            continue

        slug, lang = sub["titleSlug"], sub["lang"]
        if lang_filter and lang.lower() != lang_filter.lower():
            continue

        # Keyed by language too, so the same problem solved in Java and Python
        # is saved twice. History is newest-first, so the first hit is latest.
        key = (slug, lang_extension(lang))
        if key in seen:
            continue
        seen.add(key)

        if key in have:
            skipped += 1
            continue

        try:
            problem = fetch_problem(slug, headers)
            details = fetch_submission_code(sub["id"], headers)
            filename, _ = save_to_repo(problem, details, repo, lang)
            git_commit(repo, filename, problem["title"])
            saved.append(filename)
            print(f"  + {filename}")
        except (requests.RequestException, KeyError) as e:
            failed.append(f"{slug} ({type(e).__name__})")
            print(f"  ! {slug} — skipped: {e}")

        time.sleep(0.4)

    print("")
    print(f"Saved {len(saved)} new, left {skipped} untouched.")
    if failed:
        print(f"Failed on {len(failed)}: {', '.join(failed)}")

    if not saved:
        print("Nothing new to push.")
        return

    if no_push:
        print("Committed locally (--no-push).")
    else:
        git(repo, "push")
        print("Pushed to GitHub.")


def main():
    parser = argparse.ArgumentParser(
        description="Save a LeetCode problem + your solution to GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  leetcode-save                      # save everything new, skip what's already saved
  leetcode-save --sync-cookies       # set up / refresh your LeetCode cookies
  leetcode-save two-sum              # save one problem by slug
  leetcode-save --latest             # save just your most recent accepted problem
  leetcode-save --no-push            # commit locally without pushing

First-time setup:
  In Chrome on leetcode.com (logged in): DevTools -> Network, reload,
  right-click the top request -> Copy -> Copy as cURL.
  Then run: leetcode-save --sync-cookies

Running with no arguments walks your submission history and saves every
accepted solution missing from the repo. Files already there are left
alone, so it is safe to re-run and doubles as a first-time backfill.
        """,
    )
    parser.add_argument("slug", nargs="?", help="Problem slug, e.g. two-sum")
    parser.add_argument(
        "--sync-cookies",
        action="store_true",
        help="Set up cookies from a 'Copy as cURL' blob (clipboard, pipe, or paste)",
    )
    parser.add_argument(
        "--latest", action="store_true", help="Save only your most recent accepted submission"
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Language for a single save (default: java). Filters a full sync.",
    )
    parser.add_argument(
        "--no-push", action="store_true", help="Commit locally but don't push"
    )
    args = parser.parse_args()

    if args.sync_cookies:
        sync_cookies()
        return

    config = load_config()
    headers = make_headers(config)

    # No slug and no --latest: sync everything missing (also the first-run backfill).
    if not args.slug and not args.latest:
        sync_all(config, headers, args.no_push, lang_filter=args.lang)
        return

    lang_key = (args.lang or "java").lower()

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

    repo = config["repo_path"]
    filename, outcome = save_to_repo(
        problem, submission, repo, lang_key, version=True
    )

    if outcome == "duplicate":
        print(f"Already saved as {filename} with identical code — nothing to do.")
        return

    if outcome == "versioned":
        print(f"Saved as a new version: {filename}")
    else:
        print(f"Saved: {filename}")

    if not git_commit(repo, filename, problem["title"]):
        print("No change to commit.")
        return

    if args.no_push:
        print("Committed locally (--no-push).")
    else:
        git(repo, "push")
        print("Pushed to GitHub.")

    print(f"\nDone! ✓  #{problem['questionFrontendId']} {problem['title']}")


if __name__ == "__main__":
    main()
