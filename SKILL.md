---
name: code-walkthrough
description: Use when someone asks for a walkthrough, tour or explanation of a branch, PR or change set as a page to read or share. It builds an HTML page that shows the real code in the order it runs (or commit by commit, with a timeline between commits), with a sidebar of explanations tied to line ranges. Use it to explain code, not to review it.
---

# Code walkthrough

The skill builds a single HTML page that walks a reader through a change in the order it runs:

- an index of the steps on the left;
- the real code in the middle, with lines added by the branch marked green and lines it removed shown in red with their old line numbers;
- a sticky column of short notes on the right.

Hovering over a note highlights its lines, and clicking it scrolls to them. When a repo has a `pr`, the page links into the PR for commenting:

- Each excerpt links to its lines in the PR.
- Each line number that GitHub can take a comment on (a changed line or the 3 lines around it) opens the PR diff at that line. Shift-clicking two line numbers opens the range between them.

The links work only for code that has been pushed, so push before building. Set `pr` whenever the branch has a PR.

You write only a JSON spec. `scripts/build.py` copies the code out of the checkouts, so the code shown always matches the branch.

## Steps

1. **Find the change.** For each affected repo, note:
   - the local path;
   - the base (default `origin/master`; run `git fetch` first);
   - the PR URL, from `gh pr view <branch> --json url -q .url`. If `gh` is not installed or not logged in, use a PR URL the reader gave, or leave it empty. Without a PR the page works the same, only without the GitHub links.

   List the changed files with `git diff --stat <base>...HEAD` and the commits with `git log --reverse --oneline <base>..HEAD`.
2. **Ask which mode.** Before reading any further, ask with AskUserQuestion, naming the branch and its commit count in the question:
   - **Whole change** — one page in runtime order, showing the branch's final code against the base (the steps below).
   - **Commit by commit** — one chapter per commit with a timeline slider, showing how the code evolved (see Commit mode).

   Skip the question only when the request already names the mode ("commit by commit", "how it evolved", "the whole change"), or when the branch has a single commit (use whole change). Follow the chosen mode from here on.
3. **Read the core files fully.** Skip fixtures, lockfiles and generated files. Find the entry point: a route, CLI command, job or UI action.
4. **Plan the steps in runtime order.** Follow one request or job from start to finish: entry → validation → main work → persistence → UI. Aim for 8–15 steps. Group them into 2–4 phases, such as "Setup", "Starting a run" and "Each case".
5. **Pick the code for each step.** Use 1–4 excerpts per step, each up to about 40 lines, given as line ranges in the current file. Prefer whole functions. Put the step's most important file first.
6. **Write the notes.** Each note covers 1–3 sentences and one line range inside one excerpt.
7. **Describe the testing approach.** Fill `testing` (see Testing approach).
8. **Draw the flow.** Add a top-level Mermaid `diagram`, plus step diagrams where they help (see Diagrams).
9. **Write the spec** to `<scratchpad>/walkthrough.json` (format below).
10. **Build:**

   ```
   python3 -I ~/.claude/skills/code-walkthrough/scripts/build.py <scratchpad>/walkthrough.json <scratchpad>/walkthrough.html
   ```

   The script stops with a message if an excerpt or note points at a line that doesn't exist. Fix the spec and build again.
11. **Publish.** If the Artifact tool is available, publish the HTML with icon `code`; the build script prints the page title. Otherwise give the file path and tell the reader to open it in a browser.

To update the page after the code changes, check the line ranges in the spec, then build and publish again with the same file path.

## Commit mode

Use commit mode when the reader wants to see how the work progressed: "commit by commit", "how the code evolved", "walk me through the commits". The page gets one chapter per commit, in commit order, and shows one chapter at a time. A sticky timeline at the top, the ‹ › buttons, the ← → keys or a link like `#c2` switch chapters.

- Each excerpt is read **as the file was at that commit** (`git show <sha>:<path>`). Green and red mark only that commit's change against its parent; a file the commit adds is all green.
- When a file appears in more than one chapter, its header links to the previous and next chapter that shows it ("← commit 1", "changed again in commit 4 →"). The build adds these links.
- The commit subject, short sha and diff stat appear under the chapter title automatically.

How to write it:

1. List the commits: `git log --reverse --format='%h %s' <base>..HEAD`. One chapter per commit, unless the reader asks to skip some (fixups, formatting).
2. For each commit, read its own diff: `git show --format= <sha>`. Read the files at that commit with `git show <sha>:<path> | grep -n ""` to get the line numbers. **Line ranges refer to the file at that commit, not the working tree.** A file no later commit touches has the same numbers as HEAD.
3. Inside a chapter, order the steps by runtime, as in the default mode. Keep chapters small: 1–5 steps.
4. Let the notes tell the story between commits. Say what the previous commit left and what this one changes: "The inline `<ul>` from commit 1 becomes its own component here." When a later commit reworks the code, say so: "Commit 4 replaces this."
5. The chapter `why` says what the commit sets out to do and why, in 1–2 sentences. Don't repeat the commit subject; the page shows it already.

## Writing the notes

- **Explain, don't review.** Say what the code does and why. Don't praise it, grade it or suggest fixes. The reader wants to understand code they may not have written.
- **Write each note against the line range it covers.** Name the concrete value, status or call. For example: "Two workers share the chunk through `shift()`. Each re-reads the run before every case, so a pause takes effect within one case."
- **Link steps together** where data flows from one to another: "(step 5)", "see step 7".
- **Write for a reader who knows the stack but not this change.** Expand domain terms once, in the overview or the glossary.
- **Don't invent anything.** Check every claim against the code you read.
- **Keep secrets and personal data out of the page,** even if the code or fixtures contain them.
- **Formatting in text fields:** `` `code` ``, `**bold**` and `[label](https://url)` work. Everything else is escaped.

## Testing approach

The `testing` section comes after the steps. It gives an overview of how the change is tested. Add it to every walkthrough, even when the change has no tests, because then the reader needs to know that too.

1. **Find the test files.** List the test files the branch adds, changes or removes: `git diff --name-status <base>...HEAD`, filtered to test paths. Also search for existing tests that cover the changed code without being touched; list them too (the build marks them "unchanged").
2. **Read each test diff** (`git diff <base>...HEAD -- <test file>`). For each file, write:
   - `summary`: what the file tests, in one sentence;
   - `cases`: the test cases that were added, changed or removed, in a few words each. Say which: "Added: an empty list is current". Group many similar cases into one line.
3. **Write `paragraphs`:** 1–3 short paragraphs on the strategy. Cover which levels the change is tested at (unit, integration, end-to-end, manual) and which logic sits where. Mention any reason, visible in the code, for testing something at one level and not another.
4. **`commands`:** the commands that run the relevant tests, scoped to the changed files where the test runner allows that. Take them from `package.json`, a Makefile or the README; don't make them up.
5. **`manual`** (optional): checks done by hand, only if the conversation or the PR says they were done.
6. **`gaps`** (optional): changed behaviour that no test exercises. State the fact without judging it: "No test renders the checkbox."

The build shows each file's status (added, changed, removed, renamed or unchanged) and its line counts from git, so don't write those yourself. In commit mode it covers the whole branch, and it appears below every chapter.

## Diagrams

Add a Mermaid diagram where a picture shows the flow faster than prose. There are two places for one:

- **`diagram` at the top level:** one overview of the whole flow, placed under the overview. Add one to most walkthroughs.
- **`diagram` on a step:** only where the step itself has a shape worth drawing, such as a state machine, a request between services, or a decision ladder.

Choose the diagram type by what it shows:

| What it shows | Use |
|---|---|
| The steps of the walkthrough, with branches | `flowchart TD` or `flowchart LR` |
| Calls between services (web → api → payment provider) | `sequenceDiagram` |
| A status lifecycle | `stateDiagram-v2` |

- Keep a diagram to about 15 nodes. Split anything bigger, or leave detail to the notes.
- Label nodes with their step numbers ("3 · POST /runs") so the reader can find the matching code.
- Use the real names from the code: statuses, routes and table names.
- Don't add `style`, `classDef` or `%%{init}%%` lines. The page renders in both light and dark themes.
- Quote labels that contain parentheses, slashes or colons: `A["POST /runs (DRY)"]`.

## Spec format

```json
{
  "title": "Invoice Export Walkthrough",
  "heading": "Exporting monthly invoices to accounting",
  "eyebrow": "Code walkthrough · feature/my-branch",
  "repos": [
    { "name": "shop", "path": "/abs/path/to/shop", "base": "origin/master",
      "pr": "https://github.com/org/shop/pull/123" }
  ],
  "overview": { "heading": "How an export runs", "paragraphs": ["…", "…"] },
  "glossary": { "heading": "Job statuses", "items": [["PENDING", "Queued."], ["OK", "…"]],
                "footer": "Optional closing line." },
  "diagram": { "heading": "The flow", "mermaid": "flowchart LR\n  A[\"3 · POST /runs\"] --> B[\"6 · Worker loop\"]",
               "caption": "Optional one-line caption." },
  "phases": [
    { "title": "Setup", "steps": [
      { "title": "Schema",
        "why": "One sentence: what this step does in the flow.",
        "files": [
          { "repo": "shop", "path": "db/migrations/001.sql", "hunks": ["5-19", "37-45"] }
        ],
        "notes": [
          { "hunk": 0, "lines": "18-19", "text": "…" },
          { "hunk": 1, "lines": "44", "text": "…" }
        ] }
    ] }
  ],
  "testing": {
    "heading": "Testing approach",
    "paragraphs": ["The export query is unit tested against a seeded database; the UI only by hand."],
    "files": [
      { "repo": "shop", "path": "test/export.spec.ts", "summary": "Unit tests for the export query.",
        "cases": ["Added: skips cancelled invoices", "Changed: totals are in cents"] }
    ],
    "commands": ["npm run test:unit -- test/export.spec.ts"],
    "manual": ["Exported a month with no invoices"],
    "gaps": ["No test covers the retry after a timeout"]
  },
  "notCovered": ["Fixture PDFs"]
}
```

- `title` is the browser tab and gallery name: 2–4 words, with no explanation after a dash or colon. `heading` is the H1.
- `path` in `repos` is absolute or relative to the spec file. `base` defaults to `origin/master`, and `pr` is optional.
- In `files`, `path` is relative to the repo root. Lines are numbered as in the current working-tree file. Removed lines inside or at the edges of an excerpt appear automatically; notes can't point at them, so describe a removal in a note on the neighbouring new lines.
- Above each excerpt that starts inside a block, the build adds the lines that open the enclosing blocks (the function signature, `try {`, …), dimmed, with their line numbers and a `⋯` row where lines are skipped. It finds them by indentation and keeps at most three: the outermost and the two nearest. A line already shown by an earlier excerpt of the same file entry is not repeated. Notes can't point at them. Set `"context": false` on a file entry to turn this off.
- `hunk` in a note is the excerpt's index within the step, counting across all of the step's files in order, starting at 0.
- In `testing`, everything is optional except each file's `repo` and `path`. A file must exist in the working tree, or be removed by the change.
- `glossary`, `diagram`, `testing` and `notCovered` are optional. A step can also have `diagram`, either as an object like the top-level one or as a plain Mermaid string. It is drawn above the step's code.

`examples/walkthrough.json` is a small working spec.

Commit mode swaps `phases` for `chapters`; everything else is the same:

```json
{
  "title": "…", "heading": "…", "repos": [ … ],
  "mode": "commits",
  "overview": { … }, "glossary": { … }, "diagram": { … },
  "chapters": [
    { "repo": "shop", "commit": "a1b2c3d",
      "title": "Retry failed exports",
      "why": "What this commit sets out to do, and why.",
      "diagram": "optional mermaid",
      "steps": [ { "title": "…", "why": "…", "files": [ … ], "notes": [ … ] } ] }
  ]
}
```

- `commit` is any revision git accepts. Every file in a chapter's steps must be in the chapter's `repo`.
- `title` defaults to the commit subject.
