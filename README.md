# leetcode-save

A small CLI that archives your LeetCode solutions to a GitHub repo. Run one command after
you solve a problem and it saves a single self-contained file — your accepted code on top,
the full problem statement in a comment block below — then commits and pushes it.

One file per problem. No folders, no scattered READMEs.

```
leetcode-solutions/
├── 0001-two-sum.java
├── 0020-valid-parentheses.java
├── 0042-trapping-rain-water.java
└── 0146-lru-cache.java
```

## What a saved file looks like

```java
class Solution {
    public int[] twoSum(int[] nums, int target) {
        Map<Integer, Integer> seen = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {
            if (seen.containsKey(target - nums[i])) {
                return new int[]{seen.get(target - nums[i]), i};
            }
            seen.put(nums[i], i);
        }
        return new int[]{};
    }
}

/*
1. Two Sum
https://leetcode.com/problems/two-sum/

Difficulty : Easy
Topics     : Array, Hash Table
Runtime    : 1 ms
Memory     : 44.2 MB

------------------------------------------------------------

You are given an array of integers `nums` and an integer `target`, return indices of
the two numbers such that they add up to `target`.

Example 1:

    Input: nums = [2,7,11,15], target = 9
    Output: [0,1]
    Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].

Constraints:

  * 2 <= nums.length <= 10^4

Hints:
  1. A really brute force way would be to search for all possible pairs of numbers...
*/
```

The description lives in a comment, so the file still compiles and still opens in your
editor with syntax highlighting.

## Install

```bash
git clone https://github.com/yashwanthgh/leetcode-save.git
cd leetcode-save
bash setup.sh
```

`setup.sh` installs the Python dependencies and symlinks `leetcode-save` into the first
writable directory it finds — `~/.local/bin`, then `/opt/homebrew/bin`, then
`/usr/local/bin` — creating `~/.local/bin` if none exist. It tells you if that directory
isn't on your `PATH`. Requires Python 3.8+ and `git`.

## Setup

**1. Create a repo for your solutions** and clone it somewhere:

```bash
gh repo create leetcode-solutions --public --clone
```

**2. Create the config file:**

```bash
cp .env.example ~/.leetcode-save.env
```

**3. Set `GITHUB_REPO_PATH`** in `~/.leetcode-save.env` to wherever you cloned that repo.

**4. Grab your LeetCode cookies.** Reading your own submissions needs your session
cookie, but you don't have to go digging for it:

1. Open [leetcode.com](https://leetcode.com) in Chrome, **logged in**
2. DevTools (`Cmd+Option+I` / `F12`) → **Network** tab → reload the page
3. Right-click the top request → **Copy** → **Copy as cURL**
4. Run:

```bash
leetcode-save --sync-cookies
```

That pulls both cookies off your clipboard, verifies them against LeetCode, fills in your
username automatically, and writes everything to `~/.leetcode-save.env` with `chmod 600`.

Run the same command again whenever your session expires — the tool tells you when that
happens.

> Your cookies stay on your machine and are only ever sent to `leetcode.com`. Treat them
> like a password: they grant access to your LeetCode account. `.gitignore` blocks every
> `*.env` file so they can't be committed by accident.

## Usage

```bash
leetcode-save                      # save everything new (this is the one you'll use)
leetcode-save --latest             # save only your most recent accepted problem
leetcode-save two-sum              # save one problem by slug
leetcode-save --no-push            # commit locally, skip the push
```

Run it bare and it walks your submission history, saving every accepted solution that
isn't in the repo yet. Files already there are **never touched**, so it's safe to re-run
as often as you like — and the first run doubles as a full backfill of everything you've
already solved.

The slug is the last part of the problem URL — `leetcode.com/problems/two-sum/` → `two-sum`.

### Multiple languages

Solve the same problem in more than one language and each gets its own file:

```
0013-roman-to-integer.java
0013-roman-to-integer.cs
```

Supported: Java, Python, C, C++, C#, JavaScript, TypeScript, Go, Rust, Kotlin, Swift,
Scala, PHP, Ruby, Dart, Elixir, Erlang, Racket, and the SQL dialects. Extension and
comment style follow the language — block comments where the language has them, line
comments where it doesn't.

### Re-solving a problem

If you improve a solution and save it again, the old file stays and the new one lands
beside it:

```
0001-two-sum.java        ← your first accepted answer
0001.1-two-sum.java      ← the improved one
0001.2-two-sum.java      ← and the next
```

Re-saving identical code is a no-op, so you won't collect duplicates. A full sync keeps
one file per problem-and-language; versioning happens when you explicitly save a problem
you've already got.

## Notes

- **Session cookies expire.** When they do you'll get a message telling you to refresh
  them, not a stack trace.
- **Re-running is safe.** Saving the same problem again overwrites the file, and if
  nothing changed no empty commit is created.
- This uses LeetCode's internal GraphQL API, which is undocumented and can change
  without notice. It works today; it may need a fix someday.
- Only your *accepted* submissions are saved.

## License

MIT — see [LICENSE](LICENSE).
