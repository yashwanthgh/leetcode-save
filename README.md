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

`setup.sh` installs the Python dependencies and symlinks `leetcode-save` into
`/usr/local/bin`. Requires Python 3.8+ and `git`.

## Setup

**1. Create a repo for your solutions** and clone it somewhere:

```bash
gh repo create leetcode-solutions --public --clone
```

**2. Create the config file:**

```bash
cp .env.example ~/.leetcode-save.env
```

**3. Fill in your LeetCode cookies.** The tool reads your own submissions, which requires
your session cookie:

1. Log in at [leetcode.com](https://leetcode.com)
2. Open DevTools → **Application** → **Cookies** → `https://leetcode.com`
3. Copy the values of `LEETCODE_SESSION` and `csrftoken`

```ini
LEETCODE_SESSION=your_session_cookie
LEETCODE_CSRF=your_csrftoken
LEETCODE_USERNAME=your_username
GITHUB_REPO_PATH=/Users/you/code/leetcode-solutions
```

These cookies stay on your machine. They are only ever sent to `leetcode.com`.

## Usage

```bash
leetcode-save two-sum              # save a specific problem by its URL slug
leetcode-save --latest             # save your most recently accepted problem
leetcode-save two-sum --lang cpp   # pick a language (default: java)
leetcode-save two-sum --no-push    # commit locally, skip the push
```

The slug is the last part of the problem URL — `leetcode.com/problems/two-sum/` → `two-sum`.

### Supported languages

`java`, `python`, `python3`, `cpp`, `c`, `javascript`, `typescript`, `go`, `rust`,
`kotlin`, `swift`. The file extension and comment style follow the language.

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
