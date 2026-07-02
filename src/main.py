#!/usr/bin/env python3
import base64
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LANG_BY_EXT = {
    ".go": ("Go", "#00ADD8"),
    ".py": ("Python", "#3572A5"),
    ".ipynb": ("Jupyter Notebook", "#DA5B0B"),
    ".js": ("JavaScript", "#F1E05A"),
    ".mjs": ("JavaScript", "#F1E05A"),
    ".cjs": ("JavaScript", "#F1E05A"),
    ".ts": ("TypeScript", "#3178C6"),
    ".tsx": ("TypeScript", "#3178C6"),
    ".jsx": ("JavaScript", "#F1E05A"),
    ".vue": ("Vue", "#41B883"),
    ".java": ("Java", "#B07219"),
    ".kt": ("Kotlin", "#A97BFF"),
    ".kts": ("Kotlin", "#A97BFF"),
    ".c": ("C", "#555555"),
    ".h": ("C/C++ Header", "#555555"),
    ".cpp": ("C++", "#F34B7D"),
    ".cc": ("C++", "#F34B7D"),
    ".cxx": ("C++", "#F34B7D"),
    ".hpp": ("C++", "#F34B7D"),
    ".cs": ("C#", "#178600"),
    ".rs": ("Rust", "#DEA584"),
    ".html": ("HTML", "#E34C26"),
    ".htm": ("HTML", "#E34C26"),
    ".css": ("CSS", "#563D7C"),
    ".scss": ("SCSS", "#C6538C"),
    ".sass": ("Sass", "#A53B70"),
    ".less": ("Less", "#1D365D"),
    ".sh": ("Shell", "#89E051"),
    ".bash": ("Shell", "#89E051"),
    ".zsh": ("Shell", "#89E051"),
    ".ps1": ("PowerShell", "#012456"),
    ".yaml": ("YAML", "#CB171E"),
    ".yml": ("YAML", "#CB171E"),
    ".json": ("JSON", "#292929"),
    ".toml": ("TOML", "#9C4221"),
    ".xml": ("XML", "#0060AC"),
    ".md": ("Markdown", "#083FA1"),
    ".tex": ("TeX", "#3D6117"),
    ".r": ("R", "#198CE7"),
    ".rb": ("Ruby", "#701516"),
    ".php": ("PHP", "#4F5D95"),
    ".swift": ("Swift", "#F05138"),
    ".dart": ("Dart", "#00B4AB"),
    ".lua": ("Lua", "#000080"),
    ".gd": ("GDScript", "#355570"),
    ".dockerfile": ("Dockerfile", "#384D54"),
}

NAME_BY_FILENAME = {
    "Dockerfile": ("Dockerfile", "#384D54"),
    "Makefile": ("Makefile", "#427819"),
    "CMakeLists.txt": ("CMake", "#DA3434"),
}

DEFAULT_IGNORE = [
    ".git/**",
    ".github/**",
    "node_modules/**",
    "vendor/**",
    "dist/**",
    "build/**",
    "target/**",
    "coverage/**",
    ".next/**",
    ".nuxt/**",
    ".vite/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "go.sum",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.7z",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mp3",
    "*.wav",
    "*.onnx",
    "*.pt",
    "*.pth",
]


def run(cmd):
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def warn(message):
    print(f"[code-stats-card] {message}", file=sys.stderr)


def escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def safe_id(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", str(value))


def parse_users(raw):
    """
    Optional fallback aliases.

    Input format:
      GitHubUser=alias,email,name
      AnotherUser=another@example.com,Another Name
    """
    mapping = {}
    canonical = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        github, aliases = line.split("=", 1)
        github = github.strip()
        if not github:
            continue

        canonical[github.lower()] = github
        mapping[github.lower()] = github

        for alias in aliases.split(","):
            alias = alias.strip().strip("<>")
            if alias:
                mapping[alias.lower()] = github

    return mapping, canonical


def parse_github_user_from_email(email):
    email = (email or "").strip().strip("<>")
    match = re.match(r"(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$", email, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def normalize_user(author, email, alias_map, canonical_map):
    author = (author or "").strip()
    email = (email or "").strip().strip("<>")

    author_key = author.lower()
    email_key = email.lower()

    if email_key in alias_map:
        return alias_map[email_key]

    if author_key in alias_map:
        return alias_map[author_key]

    github_user = parse_github_user_from_email(email)
    if github_user:
        return canonical_map.get(github_user.lower(), github_user)

    return author or email or "Unknown"


def get_language(path):
    name = Path(path).name
    if name in NAME_BY_FILENAME:
        return NAME_BY_FILENAME[name]

    lower_name = name.lower()
    if lower_name == "dockerfile":
        return NAME_BY_FILENAME["Dockerfile"]

    ext = Path(path).suffix.lower()
    return LANG_BY_EXT.get(ext)


def should_ignore(path, patterns):
    normalized = path.replace("\\", "/")
    basename = Path(normalized).name

    for pattern in patterns:
        pattern = pattern.strip().replace("\\", "/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def list_files(ignore_patterns):
    raw = run(["git", "ls-files", "-z"])
    files = raw.split("\0")
    result = []

    for file in files:
        if not file:
            continue
        if should_ignore(file, ignore_patterns):
            continue
        if get_language(file) is None:
            continue
        if not Path(file).is_file():
            continue
        result.append(file)

    return result


def blame_file(path):
    """
    Return non-empty blamed lines as tuples:
      (commit_sha, fallback_author_name, fallback_author_email)
    """
    try:
        output = run(["git", "blame", "--line-porcelain", "--", path])
    except subprocess.CalledProcessError as exc:
        warn(f"skip blame failed file: {path}; {exc.stderr.strip()}")
        return []

    result = []
    current_sha = None
    current_author = None
    current_email = None

    header_re = re.compile(r"^([0-9a-f]{40})\s+")

    for line in output.splitlines():
        header = header_re.match(line)
        if header:
            current_sha = header.group(1)
            current_author = None
            current_email = None
            continue

        if line.startswith("author "):
            current_author = line[len("author "):]
        elif line.startswith("author-mail "):
            current_email = line[len("author-mail "):]
        elif line.startswith("\t"):
            content = line[1:]
            if content.strip() and current_sha:
                result.append((current_sha, current_author, current_email))

    return result


def github_api_get_json(url, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "code-stats-card",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    with urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_url_base64(url, token=None):
    headers = {"User-Agent": "code-stats-card"}
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=12) as response:
        data = response.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")


def resolve_commit_identity(repo, sha, token, commit_cache):
    """
    Resolve a commit SHA to a GitHub account through GitHub commit API.
    Returns (login, avatar_data_uri) or (None, None).
    """
    if not repo or not sha:
        return None, None
    if sha in commit_cache:
        return commit_cache[sha]

    url = f"https://api.github.com/repos/{repo}/commits/{sha}"
    try:
        data = github_api_get_json(url, token)
        account = data.get("author") or data.get("committer")
        if not account:
            commit_cache[sha] = (None, None)
            return commit_cache[sha]

        login = account.get("login")
        avatar_url = account.get("avatar_url")
        avatar = None
        if avatar_url:
            try:
                avatar = fetch_url_base64(avatar_url, token=None)
            except (HTTPError, URLError, TimeoutError, ValueError):
                avatar = None

        commit_cache[sha] = (login, avatar)
        return commit_cache[sha]
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        warn(f"commit API resolve failed for {sha[:7]}: {exc}")
        commit_cache[sha] = (None, None)
        return commit_cache[sha]


def looks_like_github_user(user):
    return bool(re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$", user or ""))


def fetch_avatar_by_login_base64(username):
    if not looks_like_github_user(username):
        return None

    try:
        url = f"https://github.com/{username}.png?size=96"
        return fetch_url_base64(url)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def lang_segments(lang_counts, total, bar_width):
    items = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
    segments = []
    used = 0.0

    for idx, (lang, count) in enumerate(items):
        if idx == len(items) - 1:
            width = max(0.0, bar_width - used)
        else:
            width = bar_width * count / total if total else 0.0
            used += width
        if width > 0.1:
            segments.append((lang, count, width))

    return segments


def generate_svg(stats, total_lines, output, width, title, min_percent):
    margin = 32
    avatar_size = 44
    row_height = 78
    top = 86
    bar_x = 250
    bar_width = max(260, width - bar_x - margin)

    users = sorted(stats.items(), key=lambda item: item[1]["total"], reverse=True)

    # MVP rule: when total contributors < 5, show everyone as a full row even if below min-percent.
    hide_small = len(users) >= 5

    visible = []
    hidden = []
    for user, data in users:
        percent = data["total"] / total_lines * 100 if total_lines else 0
        if hide_small and percent < min_percent:
            hidden.append((user, data, percent))
        else:
            visible.append((user, data, percent))

    hidden_rows = 0
    if hidden:
        hidden_rows = 70 + ((min(len(hidden), 30) + 17) // 18) * 40

    empty_height = 120 if not users else 0
    height = top + len(visible) * row_height + hidden_rows + empty_height + 28
    height = max(height, 180)

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        '<style>',
        'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}',
        '.card{fill:#ffffff;stroke:#d0d7de;stroke-width:1;}',
        '.title{font-size:26px;font-weight:700;fill:#24292f;}',
        '.sub{font-size:13px;fill:#57606a;}',
        '.name{font-size:18px;font-weight:700;fill:#24292f;}',
        '.meta{font-size:13px;fill:#57606a;}',
        '.small{font-size:12px;fill:#57606a;}',
        '</style>',
        f'<rect class="card" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="18"/>',
        f'<text class="title" x="{margin}" y="42">{escape(title)}</text>',
        f'<text class="sub" x="{margin}" y="64">{total_lines} non-empty blamed lines · {len(users)} contributors</text>',
    ]

    if not users:
        parts.append(f'<text class="meta" x="{margin}" y="110">No supported source files found.</text>')
        parts.append('</svg>')
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text("\n".join(parts), encoding="utf-8")
        return

    y = top
    for user, data, percent in visible:
        avatar = data.get("avatar")
        avatar_id = safe_id("avatar-" + user)
        cx = margin + avatar_size / 2
        cy = y + avatar_size / 2

        if avatar:
            parts.append(f'<clipPath id="{avatar_id}"><circle cx="{cx}" cy="{cy}" r="{avatar_size / 2}"/></clipPath>')
            parts.append(f'<image href="{avatar}" x="{margin}" y="{y}" width="{avatar_size}" height="{avatar_size}" clip-path="url(#{avatar_id})"/>')
        else:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{avatar_size / 2}" fill="#d0d7de"/>')
            parts.append(f'<text x="{cx}" y="{y + 29}" text-anchor="middle" font-size="16" font-weight="700" fill="#57606a">{escape(user[:1].upper())}</text>')

        parts.append(f'<text class="name" x="{margin + 60}" y="{y + 19}">{escape(user)}</text>')
        parts.append(f'<text class="meta" x="{margin + 60}" y="{y + 41}">{data["total"]} lines · {percent:.2f}%</text>')

        parts.append(f'<rect x="{bar_x}" y="{y + 8}" width="{bar_width}" height="28" rx="14" fill="#eff3f6"/>')

        x = bar_x
        segments = lang_segments(data["langs"], data["total"], bar_width)
        for idx, ((lang_name, color), count, seg_w) in enumerate(segments):
            rx = 14 if idx == 0 or idx == len(segments) - 1 else 0
            overlap = 0.5 if idx != 0 else 0
            parts.append(
                f'<rect x="{x - overlap:.2f}" y="{y + 8}" width="{seg_w + overlap:.2f}" height="28" rx="{rx}" fill="{color}"/>'
            )
            x += seg_w

        labels = []
        for (lang_name, color), count in sorted(data["langs"].items(), key=lambda item: item[1], reverse=True)[:3]:
            lang_percent = count / data["total"] * 100 if data["total"] else 0
            labels.append(f'{lang_name} {lang_percent:.1f}%')
        parts.append(f'<text class="small" x="{bar_x}" y="{y + 56}">{escape(" · ".join(labels))}</text>')

        y += row_height

    if hidden:
        y += 8
        parts.append(f'<text class="meta" x="{margin}" y="{y + 14}">Contributors below {min_percent:.2f}%</text>')
        y += 30
        x = margin
        size = 30
        gap = 10
        per_row = max(1, (width - margin * 2) // (size + gap))

        for idx, (user, data, percent) in enumerate(hidden[:30]):
            if idx > 0 and idx % per_row == 0:
                x = margin
                y += 40

            avatar = data.get("avatar")
            small_id = safe_id("small-avatar-" + user)
            cx = x + size / 2
            cy = y + size / 2
            if avatar:
                parts.append(f'<clipPath id="{small_id}"><circle cx="{cx}" cy="{cy}" r="{size / 2}"/></clipPath>')
                parts.append(f'<image href="{avatar}" x="{x}" y="{y}" width="{size}" height="{size}" clip-path="url(#{small_id})"/>')
            else:
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{size / 2}" fill="#d0d7de"/>')
            x += size + gap

        if len(hidden) > 30:
            parts.append(f'<text class="small" x="{x}" y="{y + 21}">+{len(hidden) - 30}</text>')

    parts.append('</svg>')

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(parts), encoding="utf-8")


def main():
    output = os.environ.get("INPUT_OUTPUT", "dist/code-stats.svg")
    title = os.environ.get("INPUT_TITLE", "Code Stats")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

    try:
        width = int(os.environ.get("INPUT_WIDTH", "900"))
    except ValueError:
        width = 900

    try:
        min_percent = float(os.environ.get("INPUT_MIN_PERCENT", "0.8"))
    except ValueError:
        min_percent = 0.8

    raw_ignore = os.environ.get("INPUT_IGNORE", "")
    raw_users = os.environ.get("INPUT_USERS", "")

    alias_map, canonical_map = parse_users(raw_users)
    ignore_patterns = DEFAULT_IGNORE + [line.strip() for line in raw_ignore.splitlines() if line.strip()]

    stats = defaultdict(lambda: {"total": 0, "langs": defaultdict(int), "avatar": None})
    total_lines = 0
    commit_cache = {}

    files = list_files(ignore_patterns)
    warn(f"found {len(files)} supported files")

    for file in files:
        lang = get_language(file)
        if lang is None:
            continue

        for sha, author, email in blame_file(file):
            login, avatar = resolve_commit_identity(repo, sha, token, commit_cache)
            if login:
                user = canonical_map.get(login.lower(), login)
            else:
                user = normalize_user(author, email, alias_map, canonical_map)

            stats[user]["total"] += 1
            stats[user]["langs"][lang] += 1
            total_lines += 1

            if avatar and not stats[user].get("avatar"):
                stats[user]["avatar"] = avatar

    # Fallback avatar path for users resolved through aliases / noreply parsing.
    for user in list(stats.keys()):
        if not stats[user].get("avatar"):
            stats[user]["avatar"] = fetch_avatar_by_login_base64(user)

    generate_svg(stats, total_lines, output, width, title, min_percent)
    warn(f"generated {output}")


if __name__ == "__main__":
    main()
