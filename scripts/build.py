#!/usr/bin/env python3
"""Builds a code walkthrough page from a JSON spec.

Usage: build.py <spec.json> <out.html>

Default mode: reads each excerpt from the repo's working tree, marks the lines
added since the merge base with `base`, and interleaves the lines removed since
then. Commit mode ("mode": "commits"): one chapter per commit; each excerpt is
read as it was at that commit and marked against the commit's parent. Fills
assets/template.html.
"""
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

LANGUAGES = {
    'ts': 'typescript', 'tsx': 'typescript', 'js': 'javascript', 'jsx': 'javascript', 'mjs': 'javascript',
    'cjs': 'javascript', 'sql': 'sql', 'py': 'python', 'java': 'java', 'kt': 'kotlin', 'go': 'go',
    'rb': 'ruby', 'rs': 'rust', 'cs': 'csharp', 'css': 'css', 'scss': 'scss', 'html': 'xml', 'xml': 'xml',
    'json': 'json', 'yml': 'yaml', 'yaml': 'yaml', 'sh': 'bash', 'md': 'markdown', 'php': 'php',
}


def fail(message):
    sys.exit(f'build.py: {message}')


def esc(text):
    return html.escape(str(text), quote=True)


def inline(text):
    """Escapes text, then allows `code`, **bold** and [label](https://url)."""
    out = esc(text)
    out = re.sub(r'`([^`]+)`', r'<code>\1</code>', out)
    out = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', out)
    return re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<a href="\2" target="_blank" rel="noreferrer">\1</a>', out)


def line_range(value, where):
    match = re.fullmatch(r'(\d+)(?:-(\d+))?', str(value).strip())
    if not match:
        fail(f'{where}: "{value}" is not a line or a range like 12-30')
    start, end = int(match[1]), int(match[2] or match[1])
    if end < start:
        fail(f'{where}: range {value} ends before it starts')
    return start, end


def git_try(repo, *args):
    """git output, or None if the command fails."""
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f'git {" ".join(args)} in {repo}: {result.stderr.strip()}')
    return result.stdout


def parse_diff(diff):
    """(added, removed) from a -U0 diff; see diff_lines."""
    added, removed = set(), {}
    anchor = old_no = None
    for line in diff.split('\n'):
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if match:
            old_start, new_start, new_count = int(match[1]), int(match[3]), int(match[4] or 1)
            added.update(range(new_start, new_start + new_count))
            # With no new lines, git gives the line *after which* the deletion sits.
            anchor = new_start if new_count else new_start + 1
            old_no = old_start
        elif anchor is not None and line.startswith('-') and not line.startswith('---'):
            removed.setdefault(anchor, []).append((old_no, line[1:]))
            old_no += 1
    return added, removed


def diff_lines(repo, merge_base, path, commit=None):
    """Changes in a file: in the working tree since the merge base, or, with
    `commit`, in that commit against its parent.

    Returns (added, removed). added is the set of new-file line numbers that
    differ, or None for a new file (every line is new). removed maps a
    new-file line number N to the old lines deleted just before line N, as a
    list of (old line number, text); N is one past the end for lines deleted
    at the end of the file.
    """
    if commit:
        parent = git_try(repo, 'rev-parse', '--verify', '-q', f'{commit}^')
        if parent is None or git_try(repo, 'cat-file', '-e', f'{parent.strip()}:{path}') is None:
            return None, {}
        return parse_diff(git(repo, 'diff', '-U0', '--no-color', parent.strip(), commit, '--', path))
    if merge_base is None:
        return set(), {}
    diff = git(repo, 'diff', '-U0', '--no-color', merge_base, '--', path)
    if not diff and path not in git(repo, 'ls-files', '--', path):
        return None, {}
    return parse_diff(diff)


def read_lines(repo, path, commit=None):
    """The file's lines at `commit`, or in the working tree; None if missing."""
    if commit:
        text = git_try(repo, 'show', f'{commit}:{path}')
    else:
        file_path = repo / path
        text = file_path.read_text() if file_path.is_file() else None
    if text is None:
        return None
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def compact(numbers):
    """[1,2,3,7] -> "1-3,7"."""
    parts, run = [], []
    for n in sorted(numbers):
        if run and n == run[-1] + 1:
            run.append(n)
        else:
            if run:
                parts.append(f'{run[0]}-{run[-1]}' if len(run) > 1 else str(run[0]))
            run = [n]
    if run:
        parts.append(f'{run[0]}-{run[-1]}' if len(run) > 1 else str(run[0]))
    return ','.join(parts)


MAX_CONTEXT = 3
COMMENT = re.compile(r'\s*(//|#|/\*|\*|--)')
# A line that only closes something, or ends a multi-line signature such as
# `}) {` or `): Promise<T> {`. `} else {` and the like still open a block.
CLOSER = re.compile(r'\s*(\)|[}\]](?!\s*(else|catch|finally|elif|except)\b))')


def indent(line):
    return len(line) - len(line.lstrip())


def enclosing(lines, start, end):
    """The lines that open the blocks around an excerpt, outermost first.

    Walks up from the excerpt and keeps each line indented less than
    everything seen so far, until it reaches column 0. Keeps the outermost
    line (usually the function) and the nearest ones, MAX_CONTEXT in all.
    """
    body = [l for l in lines[start - 1:end] if l.strip()]
    if not body:
        return []
    level = min(indent(l) for l in body)
    found = []
    for i in range(start - 2, -1, -1):
        if level == 0:
            break
        line = lines[i]
        if not line.strip() or indent(line) >= level or COMMENT.match(line) or CLOSER.match(line):
            continue
        found.append((i + 1, line))
        level = indent(line)
    found.reverse()
    if len(found) > MAX_CONTEXT:
        found = found[:1] + found[-(MAX_CONTEXT - 1):]
    return found


def diagram(value, where):
    """A Mermaid block: a source string, or {heading?, mermaid, caption?}."""
    d = {'mermaid': value} if isinstance(value, str) else value
    if not d.get('mermaid', '').strip():
        fail(f'{where}: diagram has no mermaid source')
    heading = f'<h2>{inline(d["heading"])}</h2>' if d.get('heading') else ''
    caption = f'<p class="caption">{inline(d["caption"])}</p>' if d.get('caption') else ''
    return f'<figure class="diagram">{heading}<pre class="mermaid">{esc(d["mermaid"].strip())}</pre>{caption}</figure>'


def file_key(repo_name, path):
    return hashlib.sha256(f'{repo_name}:{path}'.encode()).hexdigest()[:12]


def render_step(step, number, sid, where, repos, commit=None, xlinks=None):
    """One step: returns (nav item, section html).

    commit: {'repo', 'full', 'chapter'} in commit mode; files are then read at
    that commit. xlinks(repo, path) gives the cross-chapter links for a file.
    """
    hunks, files_html = [], []
    for f in step['files']:
        repo = repos.get(f['repo']) or fail(f'{where}: unknown repo "{f["repo"]}"')
        sha = None
        if commit:
            if f['repo'] != commit['repo']:
                fail(f'{where}: file in repo "{f["repo"]}", but the chapter\'s commit is in "{commit["repo"]}"')
            sha = commit['full']
        lines = read_lines(repo['path'], f['path'], sha)
        if lines is None:
            fail(f'{where}: {f["path"]} not found in {repo["name"]}' + (f' at {sha[:9]}' if sha else ''))
        changed, removed = diff_lines(repo['path'], repo['merge_base'], f['path'], sha)
        ext = f['path'].rsplit('.', 1)[-1].lower()
        anchor = hashlib.sha256(f['path'].encode()).hexdigest()
        hunk_html, shown = [], set()
        for value in f['hunks']:
            start, end = line_range(value, f'{where}, {f["path"]}')
            if end > len(lines):
                fail(f'{where}: {f["path"]} has {len(lines)} lines' + (f' at {sha[:9]}' if sha else '') +
                     f', excerpt asks for {value}')
            code = '\n'.join(lines[start - 1:end])
            if '</script' in code.lower():
                code = code.replace('</script', '<\\/script').replace('</SCRIPT', '<\\/SCRIPT')
            in_range = set(range(start, end + 1))
            marked = in_range if changed is None else in_range & changed
            link = ''
            if repo.get('pr'):
                pr = repo['pr'].rstrip('/')
                link = (f'{pr}/commits/{sha}#diff-{anchor}R{start}-R{end}' if sha
                        else f'{pr}/files#diff-{anchor}R{start}-R{end}')
            # Deleted lines that sat inside the excerpt or right at its edges
            gone = {n: rows for n, rows in removed.items() if start <= n <= end + 1}
            gone_json = json.dumps({str(n): rows for n, rows in gone.items()}, ensure_ascii=False)
            gone_json = gone_json.replace('</', '<\\/')
            context = enclosing(lines, start, end) if f.get('context', True) else []
            # An earlier excerpt of this file already showed these lines
            context = [(n, text) for n, text in context if n not in shown]
            shown.update(n for n, _ in context)
            shown.update(in_range)
            context_json = json.dumps(context, ensure_ascii=False).replace('</', '<\\/')
            hunks.append((start, end))
            hunk_html.append(
                f'<div class="hunk" data-from="{start}" data-lang="{LANGUAGES.get(ext, "")}" '
                f'data-added="{compact(marked)}" data-link="{esc(link)}">'
                f'<script type="text/x-code">\n{code}\n</script>'
                f'<script type="application/json" class="removed">{gone_json}</script>'
                f'<script type="application/json" class="context">{context_json}</script></div>')
        file_id = cross = ''
        if commit:
            key = file_key(f['repo'], f['path'])
            if key not in commit['ids']:  # links land on the file's first entry in the chapter
                commit['ids'].add(key)
                file_id = f' id="c{commit["chapter"]}-f-{key}"'
                cross = xlinks(f['repo'], f['path']) if xlinks else ''
        files_html.append(
            f'<div class="file"{file_id}><div class="fhead"><span class="repo">{esc(repo["name"])}</span>'
            f'<span class="path">{esc(f["path"])}</span>{cross}<span class="range"></span></div>{"".join(hunk_html)}</div>')

    notes = []
    for i, note in enumerate(step.get('notes', [])):
        index = note.get('hunk', 0)
        if not 0 <= index < len(hunks):
            fail(f'{where}, note {i + 1}: hunk {index} does not exist (step has {len(hunks)})')
        a, b = line_range(note['lines'], f'{where}, note {i + 1}')
        h = hunks[index]
        if a < h[0] or b > h[1]:
            fail(f'{where}, note {i + 1}: lines {note["lines"]} are outside excerpt {h[0]}-{h[1]}')
        notes.append(f'<div class="note" data-hunk="{index}" data-lines="{a}-{b}"><p>{inline(note["text"])}</p></div>')

    if step.get('diagram'):
        files_html.insert(0, diagram(step['diagram'], where))
    why = f'<p class="why">{inline(step["why"])}</p>' if step.get('why') else ''
    nav = f'<li><a href="#{sid}"><span>{number}</span>{inline(step["title"])}</a></li>'
    section = (f'<section class="step" id="{sid}"><header><span class="no">{number:02d}</span>'
               f'<h2>{inline(step["title"])}</h2>{why}</header>'
               f'<div class="code">{"".join(files_html)}</div><aside class="explain">{"".join(notes)}</aside></section>')
    return nav, section


def render_phases(spec, repos):
    """Default mode: (nav html, main html, step count)."""
    nav, steps, number = [], [], 0
    for phase in spec['phases']:
        nav.append(f'<li class="phase">{inline(phase["title"])}</li>')
        for step in phase['steps']:
            number += 1
            item, section = render_step(step, number, f's{number}', f'step {number} ({step["title"]})', repos)
            nav.append(item)
            steps.append(section)
    return f'<ol>{"".join(nav)}</ol>', ''.join(steps), number


def render_chapters(spec, repos):
    """Commit mode: (timeline html, nav html, main html, step count)."""
    chapters = spec['chapters']
    if not chapters:
        fail('commit mode needs at least one chapter')
    # Which chapters show each file, for the links between them
    seen = {}
    for ci, chapter in enumerate(chapters):
        for step in chapter['steps']:
            for f in step['files']:
                chapters_of = seen.setdefault((f['repo'], f['path']), [])
                if ci not in chapters_of:
                    chapters_of.append(ci)

    timeline, navs, sections, total = [], [], [], 0
    for ci, chapter in enumerate(chapters):
        where = f'chapter {ci + 1}'
        repo = repos.get(chapter.get('repo')) or fail(f'{where}: unknown repo "{chapter.get("repo")}"')
        full = git_try(repo['path'], 'rev-parse', '--verify', '-q', f'{chapter["commit"]}^{{commit}}')
        if full is None:
            fail(f'{where}: commit {chapter["commit"]} not found in {repo["name"]}')
        full = full.strip()
        short, subject = git(repo['path'], 'log', '-1', '--format=%h%x00%s', full).strip().split('\x00', 1)
        parent = git_try(repo['path'], 'rev-parse', '--verify', '-q', f'{full}^')
        stat = git(repo['path'], 'diff', '--shortstat', parent.strip(), full).strip() if parent else 'root commit'
        title = chapter.get('title') or subject

        def xlinks(repo_name, path, ci=ci):
            chapters_of = seen[(repo_name, path)]
            earlier = [c for c in chapters_of if c < ci]
            later = [c for c in chapters_of if c > ci]
            key = file_key(repo_name, path)
            out = []
            if earlier:
                out.append(f'<a href="#c{earlier[-1]}-f-{key}">← commit {earlier[-1] + 1}</a>')
            if later:
                out.append(f'<a href="#c{later[0]}-f-{key}">changed again in commit {later[0] + 1} →</a>')
            return f'<span class="xlinks">{"".join(out)}</span>' if out else ''

        commit = {'repo': repo['name'], 'full': full, 'chapter': ci, 'ids': set()}
        nav, steps = [], []
        for si, step in enumerate(chapter['steps']):
            item, section = render_step(step, si + 1, f'c{ci}-s{si + 1}', f'{where}, step {si + 1} ({step["title"]})',
                                        repos, commit, xlinks)
            nav.append(item)
            steps.append(section)
        total += len(chapter['steps'])

        commit_link = esc(short)
        if repo.get('pr'):
            commit_link = (f'<a href="{esc(repo["pr"].rstrip("/"))}/commits/{full}" target="_blank" '
                           f'rel="noreferrer">{esc(short)}</a>')
        why = f'<p class="why">{inline(chapter["why"])}</p>' if chapter.get('why') else ''
        diag = diagram(chapter['diagram'], where) if chapter.get('diagram') else ''
        sections.append(
            f'<section class="chapter" id="c{ci}" aria-label="Commit {ci + 1}">'
            f'<header class="chead"><p class="eyebrow">Commit {ci + 1} of {len(chapters)}</p>'
            f'<h2>{inline(title)}</h2>'
            f'<p class="subject"><code>{commit_link}</code> {esc(subject)} <span>· {esc(stat)}</span></p>{why}</header>'
            f'{diag}{"".join(steps)}</section>')
        navs.append(f'<ol data-chapter="{ci}"><li class="phase">Commit {ci + 1}</li>{"".join(nav)}</ol>')
        timeline.append(f'<li><a href="#c{ci}" title="{esc(subject)}"><span class="dot"></span>'
                        f'<code>{esc(short)}</code><span class="t">{inline(title)}</span></a></li>')

    timeline_html = (f'<nav class="timeline" aria-label="Commits"><button type="button" class="prev" '
                     f'aria-label="Previous commit">‹</button><ol>{"".join(timeline)}</ol>'
                     f'<button type="button" class="next" aria-label="Next commit">›</button></nav>')
    return timeline_html, ''.join(navs), ''.join(sections), total


def main():
    if len(sys.argv) != 3:
        fail('usage: build.py <spec.json> <out.html>')
    spec_path, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    spec = json.loads(spec_path.read_text())
    template = (Path(__file__).resolve().parent.parent / 'assets' / 'template.html').read_text()
    commit_mode = spec.get('mode') == 'commits'
    if commit_mode and 'chapters' not in spec:
        fail('"mode": "commits" needs "chapters"')
    if not commit_mode and 'phases' not in spec:
        fail('spec needs "phases" (or "mode": "commits" with "chapters")')

    repos = {}
    for repo in spec['repos']:
        path = (spec_path.parent / repo['path']).resolve()
        if not (path / '.git').exists():
            fail(f'repo {repo["name"]}: {path} is not a git checkout')
        base = repo.get('base', 'origin/master')
        merge_base = git(path, 'merge-base', base, 'HEAD').strip() if base else None
        repos[repo['name']] = {**repo, 'path': path, 'merge_base': merge_base}

    # Header
    links = []
    for repo in repos.values():
        name = f'<b>{esc(repo["name"])}</b>'
        if repo.get('pr'):
            number = repo['pr'].rstrip('/').split('/')[-1]
            name = f'<a href="{esc(repo["pr"])}" target="_blank" rel="noreferrer">{name} #{esc(number)}</a>'
        stat = git(repo['path'], 'diff', '--shortstat', repo['merge_base'], 'HEAD').strip() if repo['merge_base'] else ''
        links.append(f'<span>{name} {esc(stat)}</span>')
    header = (f'<header class="pr"><p class="eyebrow">{inline(spec.get("eyebrow", "Code walkthrough"))}</p>'
              f'<h1>{inline(spec.get("heading", spec["title"]))}</h1><div class="repos">{"".join(links)}</div></header>')

    # Overview and glossary
    panels = ''
    if spec.get('overview'):
        o = spec['overview']
        paragraphs = ''.join(f'<p>{inline(p)}</p>' for p in o.get('paragraphs', []))
        hint = 'Hover over or tap a note on the right to light up the lines it explains.'
        if commit_mode:
            hint += ' Move between commits with the timeline, or the ← → keys.'
        panels += (f'<div class="panel"><h2>{inline(o.get("heading", "How it works"))}</h2>{paragraphs}'
                   f'<p class="hint">{hint}</p></div>')
    if spec.get('glossary'):
        g = spec['glossary']
        items = ''.join(f'<dt>{inline(k)}</dt><dd>{inline(v)}</dd>' for k, v in g['items'])
        footer = f'<p>{inline(g["footer"])}</p>' if g.get('footer') else ''
        panels += f'<div class="panel"><h2>{inline(g.get("heading", "Terms"))}</h2><dl class="glossary">{items}</dl>{footer}</div>'
    overview = f'<section class="overview{"" if spec.get("glossary") else " single"}">{panels}</section>' if panels else ''
    if spec.get('diagram'):
        overview += diagram(spec['diagram'], 'top')

    if commit_mode:
        timeline, nav, main_html, number = render_chapters(spec, repos)
    else:
        timeline = ''
        nav, main_html, number = render_phases(spec, repos)

    not_covered = ''
    if spec.get('notCovered'):
        items = ''.join(f'<li>{inline(x)}</li>' for x in spec['notCovered'])
        not_covered = f'<div class="out"><b>Not covered here</b><ul>{items}</ul></div>'

    content = (f'{header}{overview}{timeline}<div class="layout{" commits" if commit_mode else ""}">'
               f'<nav class="side" aria-label="Walkthrough">{nav}</nav>'
               f'<main>{main_html}{not_covered}</main></div>')
    page = template.replace('{{TITLE}}', esc(spec['title'])).replace('{{CONTENT}}', content)
    out_path.write_text(page)
    chapters = f'{len(spec["chapters"])} commits, ' if commit_mode else ''
    print(f'Built {out_path} ({chapters}{number} steps, {len(page) // 1024} KB). Title: {spec["title"]}')


if __name__ == '__main__':
    main()
