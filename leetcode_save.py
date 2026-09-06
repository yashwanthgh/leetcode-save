#!/usr/bin/env python3
"""leetcode-save: fetch a LeetCode problem + your accepted solution and commit to GitHub."""

import os
import re
import sys
import json
import time
import queue
import shutil
import platform
import threading
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
    lines = (
        CONFIG_PATH.read_text(encoding="utf-8").splitlines()
        if CONFIG_PATH.exists()
        else []
    )
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

    write_lf(CONFIG_PATH, "\n".join(out) + "\n")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        # Windows has no POSIX mode bits; the file is still user-scoped.
        pass


def write_lf(path, content):
    """Write UTF-8 with LF endings.

    Path.write_text only accepts newline= from Python 3.10, and the platform
    default would give CRLF on Windows.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


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


def copy_steps():
    devtools = "Cmd+Option+I" if platform.system() == "Darwin" else "F12"
    reload_key = "Cmd+R" if platform.system() == "Darwin" else "Ctrl+R"
    return f"""To log in, this needs one thing out of your browser.

In your browser, go to leetcode.com and make sure you are logged in. Then:

  1. Press {devtools} to open the developer tools
  2. Click the "Network" tab along the top
  3. Reload the page ({reload_key}) -- a list of requests appears
  4. Right-click the first request in that list
  5. Choose  Copy  ->  Copy as cURL

Nothing is shown to you at that point; it just goes on your clipboard.
Chrome, Edge and Firefox all have this."""


def extract_cookies(raw):
    session = re.search(r"LEETCODE_SESSION=([^;'\"\s]+)", raw)
    csrf = re.search(r"csrftoken=([^;'\"\s]+)", raw)
    if session and csrf:
        return session.group(1), csrf.group(1)
    return None


def read_clipboard():
    """Best-effort clipboard read. Returns '' when there's no way to do it."""
    system = platform.system()
    if system == "Darwin":
        cmds = [["pbpaste"]]
    elif system == "Windows":
        cmds = [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]
    else:
        cmds = [
            ["wl-paste"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ]

    for cmd in cmds:
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout

    return ""


class StdinReader:
    """One reader thread for the whole process.

    A thread blocked in sys.stdin cannot be cancelled, so a second reader
    would race it and swallow whatever the user types next. Everything that
    needs stdin goes through this single queue instead. Reading on a thread
    rather than via select() also keeps Windows working, where select()
    accepts only sockets.
    """

    def __init__(self):
        self._queue = queue.Queue()
        self._started = False
        self._done = False

    def _start(self):
        if self._started:
            return
        self._started = True

        def reader():
            try:
                for line in sys.stdin:
                    self._queue.put(line)
            except Exception:
                pass
            self._queue.put(None)

        threading.Thread(target=reader, daemon=True).start()

    def line(self, timeout=None):
        """Next line, or None if input ended or the wait ran out."""
        if self._done:
            return None
        self._start()
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            self._done = True
            return None
        return item.rstrip("\r\n")

    def burst(self, idle=0.6, wait=300):
        """Everything from one paste. Ends when input goes quiet."""
        first = self.line(timeout=wait)
        if first is None:
            return ""
        chunks = [first]
        while True:
            item = self.line(timeout=idle)
            if item is None:
                break
            chunks.append(item)
        return "\n".join(chunks)


STDIN = StdinReader()


def ask(prompt, timeout=300):
    """Prompt for one line. Returns None if input ended or timed out."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    answer = STDIN.line(timeout=timeout)
    if answer is None:
        print("")
    return answer


def sync_cookies(paste=False):
    """Set up cookies from a 'Copy as cURL' blob: pasted, piped, or on the clipboard."""
    found = None

    if not paste:
        found = extract_cookies(read_clipboard())
        if found:
            print("Found your login on the clipboard.")

    if not found:
        # No isatty() check here: in Git Bash and other MSYS terminals stdin
        # is a pipe, so trusting isatty() would skip the prompt and block
        # silently. A burst read handles piped input and typing alike.
        print(copy_steps())
        print("")
        print("Then come back here, paste it, and press Enter.")
        print("It will look like a huge wall of text. That is expected.")
        print("")
        print("Waiting for your paste...")
        print("")
        try:
            found = extract_cookies(STDIN.burst())
        except KeyboardInterrupt:
            print("")
            sys.exit(1)

    if not found:
        print("")
        print("That paste didn't contain a LeetCode login.")
        print("")
        print("Two things to check:")
        print("  - You were logged in to leetcode.com when you copied it")
        print("  - You picked a request from leetcode.com, not from another site")
        print("")
        print("Try again with:  leetcode-save --login")
        sys.exit(1)

    session, csrf = found

    print("Got it. Checking with LeetCode...")
    user = whoami(session, csrf)
    if not user:
        print("")
        print("LeetCode didn't accept that login.")
        print("It's usually because you weren't signed in in that browser,")
        print("or the copied request was already expired. Log in at")
        print("leetcode.com, then try again with:  leetcode-save --login")
        sys.exit(1)

    write_config_values(
        {
            "LEETCODE_SESSION": session,
            "LEETCODE_CSRF": csrf,
            "LEETCODE_USERNAME": user,
        }
    )
    print(f"Signed in as '{user}'.")

    if not valid_repo_path(os.getenv("GITHUB_REPO_PATH")):
        resolve_repo_path()

    print("")
    print("You're all set. From now on, after you solve a problem:")
    print("")
    print("    leetcode-save")
    print("")
    print("That's the only command you need. This login lasts a few weeks;")
    print("when it runs out the tool will tell you to run --login again.")


def valid_repo_path(raw):
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if (p / ".git").is_dir() else None


SEARCH_ROOTS = (
    "",
    "Desktop",
    "Documents",
    "code",
    "Code",
    "Projects",
    "projects",
    "repos",
    "dev",
    "src",
    "git",
    "GitHub",
    "github",
    # Windows "Known Folder Move" relocates these into OneDrive, so the
    # plain Desktop and Documents above may not exist at all.
    "OneDrive",
    "OneDrive/Desktop",
    "OneDrive/Documents",
)


def find_repo_candidates():
    """Look for an already-cloned solutions repo in the usual places."""
    found, seen = [], set()

    def consider(p):
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen:
            return
        seen.add(rp)
        if not (rp / ".git").is_dir():
            return
        # Don't offer this tool's own checkout as a place to store solutions.
        if (rp / "leetcode_save.py").exists():
            return
        if "leetcode" not in rp.name.lower().replace("-", "").replace("_", "").replace(" ", ""):
            return
        found.append(rp)

    consider(Path.cwd())
    for name in SEARCH_ROOTS:
        root = Path.home() / name if name else Path.home()
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for c in children:
            try:
                if c.is_dir():
                    consider(c)
            except OSError:
                continue

    return found


def create_repo():
    """Offer to make the solutions repo, since gh can do it in one shot."""
    name = "leetcode-solutions"
    target = Path.home() / name

    if not shutil.which("gh"):
        print("GitHub CLI ('gh') isn't installed, so I can't create the repo for you.")
        return None

    print(f"I can create '{name}' on GitHub and clone it to {target}.")
    answer = ask("Do that now? [Y/n]: ")
    if answer is None:
        return None
    if answer.strip().lower() in ("n", "no"):
        return None

    try:
        result = subprocess.run(
            ["gh", "repo", "create", name, "--public", "--clone"],
            cwd=Path.home(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  Couldn't run gh: {e}")
        return None

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        print(f"  Couldn't create it: {detail[-1] if detail else 'gh gave no reason'}")
        print("  You can create one yourself and point me at it instead.")
        return None

    if not (target / ".git").is_dir():
        print(f"  gh reported success but {target} isn't there.")
        print("  Point me at the clone yourself instead.")
        return None

    # A brand new repo has no commits, so give it one and set upstream.
    write_lf(
        target / "README.md",
        "# LeetCode Solutions\n\nSaved with "
        "[leetcode-save](https://github.com/yashwanthgh/leetcode-save).\n",
    )
    git(target, "add", "README.md")
    git(target, "commit", "-m", "Add README")
    git(target, "branch", "-M", "main")
    git(target, "push", "-u", "origin", "main")

    print(f"  Created and cloned to {target}")
    return target


def ask_for_path():
    for _ in range(3):
        answer = ask("Path to your solutions repo: ")
        if answer is None:
            return None
        answer = answer.strip().strip('"').strip("'")
        if not answer:
            continue
        repo = Path(answer).expanduser()
        if not repo.is_dir():
            print(f"  No such folder: {repo}")
            continue
        if not (repo / ".git").is_dir():
            print(f"  {repo} isn't a git repo - clone it from GitHub first.")
            continue
        return repo
    return None


def resolve_repo_path(interactive=True):
    """Work out where solutions go, asking as little as possible.

    A single obvious candidate needs no input at all, so this works even
    when there is no terminal to prompt on.
    """
    candidates = find_repo_candidates()

    if len(candidates) == 1:
        repo = candidates[0]
        print(f"Using solutions repo: {repo}")
        write_config_values({"GITHUB_REPO_PATH": str(repo)})
        return repo

    if not interactive:
        return None

    if len(candidates) > 1:
        print("Found more than one repo that could hold your solutions:")
        for i, c in enumerate(candidates, 1):
            print(f"  {i}. {c}")
        print("")
        repo = None
        for _ in range(3):
            pick = ask(f"Which one? [1-{len(candidates)}]: ")
            if pick is None:
                return None
            pick = pick.strip()
            if pick.isdigit() and 1 <= int(pick) <= len(candidates):
                repo = candidates[int(pick) - 1]
                break
            print("  Enter one of the numbers above.")
        if repo is None:
            sys.exit(1)
    else:
        print("")
        print("You don't seem to have a repo for your solutions yet.")
        repo = create_repo() or ask_for_path()
        if repo is None:
            print("Giving up. Re-run: leetcode-save --login")
            sys.exit(1)

    write_config_values({"GITHUB_REPO_PATH": str(repo)})
    return repo


def load_config():
    config_path = CONFIG_PATH
    if config_path.exists():
        load_dotenv(config_path)
    else:
        load_dotenv()

    session = os.getenv("LEETCODE_SESSION")
    csrf = os.getenv("LEETCODE_CSRF")
    username = os.getenv("LEETCODE_USERNAME", "")

    if not session or not csrf:
        print("You're not logged in yet.")
        print("")
        print("Run:  leetcode-save --login")
        sys.exit(1)

    repo = valid_repo_path(os.getenv("GITHUB_REPO_PATH"))
    if not repo:
        repo = resolve_repo_path(interactive=sys.stdin.isatty())
    if not repo:
        print("Couldn't work out where to save your solutions.")
        print("Run:  leetcode-save --login")
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
    print("")
    print("Your LeetCode login has expired. This happens every few weeks.")
    print("")
    print("To fix it, run:")
    print("")
    print("    leetcode-save --login")
    print("")
    print("It will walk you through it. Nothing you've saved is affected.")
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
            "variables": {"questionSlug": slug, "offset": 0, "limit": 100},
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


def fetch_recent_accepted(lang_key, headers, scan=100):
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
    text = text.replace("\u00a0", " ")  # nbsp
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

    folder = repo_path / folder_for_ext(ext)
    folder.mkdir(exist_ok=True)
    base = folder / f"{num}-{slug}.{ext}"
    rel = lambda p: p.relative_to(repo_path).as_posix()

    if not base.exists():
        write_lf(base, content)
        return rel(base), "new"

    if not version:
        write_lf(base, content)
        return rel(base), "updated"

    # Runtime and memory differ between runs, so compare only the code itself.
    code = submission_details["code"].rstrip()
    for f in sorted(folder.glob(f"{num}*-{slug}.{ext}")):
        if f.read_text(encoding="utf-8").startswith(code):
            return rel(f), "duplicate"

    n = 1
    while (folder / f"{num}.{n}-{slug}.{ext}").exists():
        n += 1
    versioned = folder / f"{num}.{n}-{slug}.{ext}"
    write_lf(versioned, content)
    return rel(versioned), "versioned"


def show_version():
    """Print which copy of the script is running, and how current it is."""
    script = Path(__file__).resolve()
    print(f"script : {script}")

    here = script.parent
    commit = git(here, "log", "-1", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M",
                 check=False)
    if commit:
        print(f"commit : {commit}")
        behind = git(here, "rev-list", "--count", "HEAD..@{u}", check=False)
        if behind.isdigit() and int(behind) > 0:
            print(f"         {behind} commit(s) behind origin - run: git -C '{here}' pull")
        elif behind == "0":
            print("         up to date")
    else:
        print("commit : not a git checkout, so it can't be updated with git pull")

    print(f"python : {'.'.join(map(str, sys.version_info[:3]))}")
    print(f"config : {CONFIG_PATH}")
    repo = os.getenv("GITHUB_REPO_PATH")
    print(f"repo   : {repo or '(not set yet)'}")
    print("layout : code/ and sql/")


def require_git():
    if not shutil.which("git"):
        print("git isn't installed, or isn't on your PATH.")
        print("Your solutions are stored in a git repo, so it's required.")
        if platform.system() == "Windows":
            print("Get it from https://git-scm.com/download/win")
        elif platform.system() == "Darwin":
            print("Install it with:  xcode-select --install")
        else:
            print("Install it with your package manager, e.g. apt install git")
        sys.exit(1)


def git(repo_path, *cmd, check=True, timeout=120):
    try:
        result = subprocess.run(
            ["git", *cmd],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        require_git()
    except subprocess.TimeoutExpired:
        # capture_output swallows any credential or passphrase prompt, so a
        # hung command looks like a freeze with no explanation.
        print(f"git {cmd[0]} timed out after {timeout}s.")
        print("If it was waiting for a password, set up credential caching")
        print("or an SSH key, then try again.")
        sys.exit(1)

    if check and result.returncode != 0:
        print(f"git {cmd[0]} failed: {result.stderr.strip() or 'no output'}")
        sys.exit(1)
    return result.stdout.strip()


def remote_default_branch(repo_path):
    """The branch name the remote treats as its default, if it says."""
    out = git(
        repo_path, "ls-remote", "--symref", "origin", "HEAD", check=False, timeout=60
    )
    m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", out, re.MULTILINE)
    return m.group(1) if m else None


def first_push_branch(repo_path):
    """Branch to push on a first push, renaming a stale local name to match.

    'git init' still calls the first branch 'master' while GitHub calls it
    'main', so pushing blind would put solutions on a side branch that the
    repo's front page never shows. Renaming is only safe here because
    nothing has been pushed from this branch yet.
    """
    branch = git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    target = remote_default_branch(repo_path) or "main"

    if branch == target:
        return branch

    existing = git(repo_path, "branch", "--format=%(refname:short)", check=False)
    if target in existing.splitlines():
        # Renaming would clobber a real branch; leave well alone.
        print(f"Note: pushing '{branch}', but the repo's default is '{target}'.")
        return branch

    print(f"Renaming branch '{branch}' to '{target}' to match GitHub.")
    git(repo_path, "branch", "-M", target)
    return target


def git_push(repo_path):
    """Push, setting upstream on the first push if the branch has none."""
    result = subprocess.run(
        ["git", "push"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode == 0:
        return True

    stderr = result.stderr or ""

    if not git(repo_path, "remote", check=False):
        print("This repo isn't connected to GitHub, so there's nowhere to push.")
        print("Your solutions are committed on this computer and safe.")
        print("")
        print("Connect it, then run leetcode-save again:")
        print(f"  cd {repo_path}")
        print("  git remote add origin <your repo url>")
        return False

    # A freshly created or freshly init'd repo has no tracking branch yet,
    # which plain 'git push' refuses to guess at.
    if "no upstream branch" in stderr or "No configured push destination" in stderr:
        branch = first_push_branch(repo_path)
        print(f"First push from this repo - linking '{branch}' to origin.")
        git(repo_path, "push", "-u", "origin", branch, timeout=180)
        return True

    print(f"git push failed: {result.stderr.strip() or 'no output'}")
    print("Your solutions are committed locally, so nothing is lost.")
    print("Fix the problem above, then run leetcode-save again to upload them.")
    return False


def unpushed_count(repo_path):
    """Commits sitting locally that the remote doesn't have yet."""
    upstream = git(repo_path, "rev-parse", "--abbrev-ref", "@{u}", check=False)
    if not upstream:
        # No upstream means nothing has ever been pushed from this branch.
        return len(git(repo_path, "log", "--format=%h", check=False).splitlines())
    out = git(repo_path, "rev-list", "--count", "@{u}..HEAD", check=False)
    return int(out) if out.isdigit() else 0


def remote_url(repo_path):
    """Browsable URL for the repo's origin, if it has a recognisable one."""
    url = git(repo_path, "remote", "get-url", "origin", check=False)
    if not url:
        return None
    url = url.strip()
    if url.startswith("git@"):
        # git@github.com:user/repo.git -> https://github.com/user/repo
        host, _, path = url[4:].partition(":")
        url = f"https://{host}/{path}"
    return url[:-4] if url.endswith(".git") else url


def git_commit(repo_path, filename, problem_title):
    """Stage and commit one file. Returns False if it produced no change."""
    git(repo_path, "add", "--", filename)

    # Scoped to this file on purpose: a repo-wide status would also see
    # unrelated stray files like .DS_Store and report a change that isn't
    # staged, making the commit below fail and abort a whole backfill.
    unchanged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", filename],
        cwd=repo_path,
        capture_output=True,
    ).returncode == 0
    if unchanged:
        return False

    # Pathspec form so only this file is committed, whatever else is lying around.
    git(repo_path, "commit", "-m", f"solve: {problem_title}", "--", filename)
    return True


SOLUTION_FILE = re.compile(r"^\d+(?:\.\d+)?-(.+)\.([^.]+)$")

SQL_FOLDER = "sql"
CODE_FOLDER = "code"


def folder_for_ext(ext):
    return SQL_FOLDER if ext.lower() == "sql" else CODE_FOLDER


def iter_solution_files(repo_path):
    """Every solution file, in the folders and loose in the root alike."""
    roots = [repo_path, repo_path / CODE_FOLDER, repo_path / SQL_FOLDER]
    for root in roots:
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for f in entries:
            if not f.is_file():
                continue
            m = SOLUTION_FILE.match(f.name)
            if m:
                yield f, m.group(1), m.group(2)


def existing_solutions(repo_path):
    """(slug, extension) pairs already saved, read straight off the filenames."""
    return {(slug, ext) for _, slug, ext in iter_solution_files(repo_path)}


def migrate_layout(repo_path):
    """Move solution files that predate the code/ and sql/ split.

    Uses 'git mv' so history follows the file. Returns how many moved.
    """
    moves = []
    for f in list(iter_solution_files(repo_path)):
        path, _, ext = f
        if path.parent != repo_path:
            continue
        dest = repo_path / folder_for_ext(ext) / path.name
        if dest.exists():
            continue
        moves.append((path, dest))

    if not moves:
        return 0

    print(f"Tidying up: moving {len(moves)} solution(s) into code/ and sql/")
    for src, dest in moves:
        dest.parent.mkdir(exist_ok=True)
        rel_src = src.relative_to(repo_path).as_posix()
        rel_dest = dest.relative_to(repo_path).as_posix()
        git(repo_path, "mv", "--", rel_src, rel_dest, check=False)
        if not dest.exists():
            # Untracked files aren't git mv-able; move then stage by hand.
            shutil.move(str(src), str(dest))
            git(repo_path, "add", "--", rel_dest)

    git(repo_path, "add", "-A", "--", ".")
    git(repo_path, "commit", "-m", "Sort solutions into code/ and sql/")
    print("  done")
    return len(moves)


def iter_submissions(headers, page=20, max_pages=250):
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
    print(f"Saving to: {repo}")

    migrate_layout(repo)

    have = existing_solutions(repo)
    print(f"Already there: {len(have)} solution(s)")
    print("")
    print("Checking LeetCode for anything new...")

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
            print(f"  ! {slug} - skipped: {e}")

        time.sleep(0.4)

    print("")
    if failed:
        print(f"Couldn't save {len(failed)}: {', '.join(failed)}")
        print("Those are usually temporary - try again in a minute.")
        print("")

    if saved:
        print(f"Saved {len(saved)} new solution(s). Left the other {skipped} alone.")
    else:
        print(f"Nothing new to save. All {skipped} of your solutions are")
        print("already in the repo, and none of them were touched.")

    if no_push:
        print("")
        print("Committed on this computer only, because you passed --no-push.")
        print("Run 'leetcode-save' again without it to upload them.")
        return

    # Not gated on `saved`: an earlier run may have committed fine but failed
    # to push, and those commits would otherwise never be uploaded.
    pending = unpushed_count(repo)
    if not pending:
        return

    if not saved:
        print("")
        print(f"But {pending} earlier commit(s) were never uploaded.")

    print("Uploading to GitHub...")
    if not git_push(repo):
        return
    print("Done.")

    url = remote_url(repo)
    if url:
        print("")
        print(f"See them at {url}")


def main():
    parser = argparse.ArgumentParser(
        description="Save a LeetCode problem + your solution to GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  leetcode-save                      # save everything new, skip what's already saved
  leetcode-save --login              # log in: paste a Copy-as-cURL blob
  leetcode-save two-sum              # save one problem by slug
  leetcode-save --latest             # save just your most recent accepted problem
  leetcode-save --no-push            # commit locally without pushing

First-time setup:
  In Chrome on leetcode.com (logged in): DevTools -> Network, reload,
  right-click the top request -> Copy -> Copy as cURL.
  Then run: leetcode-save --login

Running with no arguments walks your submission history and saves every
accepted solution missing from the repo. Files already there are left
alone, so it is safe to re-run and doubles as a first-time backfill.
        """,
    )
    parser.add_argument("slug", nargs="?", help="Problem slug, e.g. two-sum")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show which copy of the script is running and whether it's current",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Log in: paste a 'Copy as cURL' blob when prompted",
    )
    parser.add_argument(
        "--sync-cookies",
        action="store_true",
        help="Same as --login, but checks the clipboard first",
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

    require_git()

    if args.version:
        load_dotenv(CONFIG_PATH) if CONFIG_PATH.exists() else None
        show_version()
        return

    if args.login or args.sync_cookies:
        sync_cookies(paste=args.login)
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
        print(f"  -> {recent['title']}")
    else:
        slug, sub_id = args.slug, None

    print(f"Fetching problem: {slug}")
    problem = fetch_problem(slug, headers)
    print(f"  -> #{problem['questionFrontendId']} {problem['title']} ({problem['difficulty']})")

    if sub_id is None:
        print(f"Looking for your accepted {lang_key} submission...")
        sub_id = fetch_submission_id(slug, lang_key, headers)
        if not sub_id:
            print(f"No accepted {lang_key} submission found for '{slug}'.")
            print("Tip: make sure you've submitted and it passed on leetcode.com")
            sys.exit(1)

    submission = fetch_submission_code(sub_id, headers)
    print(
        f"  -> Runtime: {submission.get('runtimeDisplay', 'N/A')}"
        f"  Memory: {submission.get('memoryDisplay', 'N/A')}"
    )

    repo = config["repo_path"]
    filename, outcome = save_to_repo(
        problem, submission, repo, lang_key, version=True
    )

    if outcome == "duplicate":
        print(f"Already saved as {filename} with identical code - nothing to do.")
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
        if not git_push(repo):
            return
        print("Pushed to GitHub.")

    print(f"\nDone! #{problem['questionFrontendId']} {problem['title']}")


if __name__ == "__main__":
    main()
