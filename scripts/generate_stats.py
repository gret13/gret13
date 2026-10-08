"""Generate an aggregated GitHub SVG statistics card.

Requires STATS_TOKEN with read access to the relevant private repositories.
Counts commits by GitHub author on the default branch of each repository.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

API = "https://api.github.com"
USER = "gret13"
ORG = "eklimov-dev-ru"
COLORS = ["#E5B64A", "#58A6FF", "#3FB950", "#BC8CFF", "#F78166", "#79C0FF"]


def get_json(path: str, params: dict[str, object] | None = None) -> tuple[object, dict[str, str]]:
    token = os.environ.get("STATS_TOKEN")
    if not token:
        raise RuntimeError("STATS_TOKEN is required to include private repositories")
    url = f"{API}{path}"
    if params:
        url += "?" + urlencode(params)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gret13-github-stats",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
            return data, dict(response.headers)
    except HTTPError as exc:
        raise RuntimeError(f"GitHub API returned HTTP {exc.code} for {path}") from exc


def pages(path: str, params: dict[str, object] | None = None):
    page = 1
    while True:
        arguments = {"per_page": 100, "page": page, **(params or {})}
        data, _ = get_json(path, arguments)
        if not isinstance(data, list):
            raise RuntimeError(f"Expected a list from {path}")
        yield from data
        if len(data) < 100:
            break
        page += 1


def repositories() -> list[dict]:
    # Membership permissions must allow listing private organization repositories.
    result: dict[str, dict] = {}
    for path in (f"/users/{USER}/repos", f"/orgs/{ORG}/repos"):
        for repo in pages(path, {"type": "all"}):
            if repo["owner"]["login"].lower() in (USER.lower(), ORG.lower()):
                result[repo["full_name"]] = repo
    # The /user/repos endpoint includes private repositories owned by the user.
    for repo in pages("/user/repos", {"affiliation": "owner", "visibility": "all"}):
        if repo["owner"]["login"].lower() == USER.lower():
            result[repo["full_name"]] = repo
    # /user/orgs is insufficient to establish access to every private org repo.
    # Org-owned repositories must be accessible via the organization listing endpoint.
    return list(result.values())


def pull_requests(owner: str) -> int:
    data, _ = get_json(
        "/search/issues",
        {"q": f"type:pr author:{USER} {owner}:{USER if owner == 'user' else ORG}", "per_page": 1},
    )
    return int(data["total_count"])


def aggregate(repo_list: list[dict]) -> tuple[int, Counter[str]]:
    commits = 0
    languages: Counter[str] = Counter()
    for repo in repo_list:
        name = repo["full_name"]
        for _ in pages(f"/repos/{name}/commits", {"author": USER, "sha": repo["default_branch"]}):
            commits += 1
        data, _ = get_json(f"/repos/{name}/languages")
        languages.update({name: int(size) for name, size in data.items()})
    return commits, languages


def render(commits: int, prs: int, repos: int, languages: Counter[str]) -> str:
    ordered = sorted(languages.items(), key=lambda p: (-p[1], p[0]))
    height = 185 + len(ordered) * 30
    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="680" height="{height}" viewBox="0 0 680 {height}">',
        '<rect x="1" y="1" width="678" height="' + str(height - 2) + '" rx="15" fill="#0d1117" stroke="#30363d"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif}</style>',
        '<text x="30" y="43" font-size="23" font-weight="bold" fill="#E5B64A">GreT13 · GitHub Statistics</text>',
        '<text x="30" y="67" font-size="12" fill="#8b949e">Personal + eklimov-dev-ru · All time</text>',
    ]
    for i, (label, value) in enumerate((("COMMITS", commits), ("PULL REQUESTS", prs), ("REPOSITORIES", repos))):
        x = 30 + i * 218
        fragments.extend([
            f'<text x="{x}" y="99" font-size="12" fill="#8b949e">{label}</text>',
            f'<text x="{x}" y="128" font-size="25" font-weight="bold" fill="#f0f6fc">{value:,}</text>',
        ])
    fragments.append('<text x="30" y="168" font-size="16" font-weight="bold" fill="#E5B64A">All Languages</text>')
    total = sum(languages.values())
    for i, (name, size) in enumerate(ordered):
        y = 194 + i * 30
        pct = 100 * size / total if total else 0
        color = COLORS[i % len(COLORS)]
        fragments.extend([
            f'<text x="30" y="{y}" font-size="13" fill="#c9d1d9">{escape(name)}</text>',
            f'<text x="637" y="{y}" text-anchor="end" font-size="13" fill="#c9d1d9">{pct:.1f}%</text>',
            f'<rect x="215" y="{y - 11}" width="350" height="10" rx="5" fill="#21262d"/>',
            f'<rect x="215" y="{y - 11}" width="{350 * size / total if total else 0:.2f}" height="10" rx="5" fill="{color}"/>',
        ])
    fragments.append("</svg>")
    return "\n".join(fragments) + "\n"


def main() -> None:
    repos = repositories()
    if not repos:
        raise RuntimeError("No repositories found: check STATS_TOKEN permissions")
    commits, langs = aggregate(repos)
    prs = pull_requests("user") + pull_requests("org")
    output = Path("dist/github-statistics.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(commits, prs, len(repos), langs), encoding="utf-8")


if __name__ == "__main__":
    main()
