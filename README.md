# code-walkthrough

A Claude Code skill that turns a branch or PR into a single HTML page: the real code in the order it runs (or commit by commit), with a sidebar of notes tied to line ranges.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3 (standard library only)
- `git`
- `gh` (optional: finds the PR URL for the GitHub links; without it, give the PR URL yourself or go without the links)

## Install

Clone this repo into your Claude Code skills directory:

```sh
git clone <repo-url> ~/.claude/skills/code-walkthrough
```

To install for one project only, clone into `<project>/.claude/skills/code-walkthrough` instead.

Restart Claude Code. The skill shows up as `code-walkthrough`.

## Use

In a repo with a branch checked out, ask Claude:

> Make a walkthrough of this branch.

Or call it directly with `/code-walkthrough`.
