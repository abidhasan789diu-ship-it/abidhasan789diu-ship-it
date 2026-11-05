#!/usr/bin/env python3
"""Build profile analytics SVGs from GitHub's documented REST and GraphQL APIs."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

USERNAME = os.environ.get("GITHUB_USERNAME", "abidhasan789diu-ship-it")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
REST_API = "https://api.github.com"
GRAPHQL_API = "https://api.github.com/graphql"
OUT = Path("assets")
BG, PANEL, TEXT, MUTED = "#0D1117", "#161B22", "#E6EDF3", "#9AA7B5"
CYAN, PURPLE, PINK = "#00F5FF", "#8B5CF6", "#FF00FF"
PALETTE = [CYAN, PURPLE, PINK, "#38BDF8", "#A78BFA", "#F472B6", "#22D3EE", "#C084FC"]


class GitHubError(RuntimeError):
    """Raised when upstream GitHub data cannot be safely used."""


def request_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{USERNAME}-profile-analytics",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
            if isinstance(result, dict) and result.get("errors"):
                raise GitHubError(f"GitHub API errors: {result['errors']}")
            return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (403, 429) and attempt < 3:
                retry_after = exc.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                time.sleep(max(1, min(wait, 60)))
                continue
            raise GitHubError(f"GitHub API returned HTTP {exc.code}: {detail[:600]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise GitHubError(f"Network request failed: {exc}") from exc
            time.sleep(2 ** attempt)
    raise GitHubError(f"Unable to retrieve {url}")


def get_user() -> dict[str, Any]:
    result = request_json(f"{REST_API}/users/{urllib.parse.quote(USERNAME)}")
    if result.get("login", "").lower() != USERNAME.lower():
        raise GitHubError("GitHub returned a different account.")
    return result


def get_repositories() -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request_json(
            f"{REST_API}/users/{urllib.parse.quote(USERNAME)}/repos"
            f"?type=owner&sort=updated&per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise GitHubError("Unexpected response while listing public repositories.")
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [
        repo for repo in repositories
        if not repo.get("fork") and not repo.get("private") and not repo.get("archived")
    ]


def get_languages(repositories: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for repo in repositories:
        url = repo.get("languages_url")
        if not url:
            continue
        result = request_json(url)
        if not isinstance(result, dict):
            raise GitHubError(f"Invalid language response for {repo.get('full_name')}.")
        for name, byte_count in result.items():
            if isinstance(byte_count, int) and byte_count >= 0:
                totals[name] += byte_count
    return dict(totals)


def get_contribution_calendar() -> dict[str, Any]:
    if not TOKEN:
        raise GitHubError("GH_TOKEN is missing; a token is required for the GitHub GraphQL API.")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    result = request_json(GRAPHQL_API, {
        "query": query,
        "variables": {
            "login": USERNAME,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
    })
    user = (result.get("data") or {}).get("user")
    if not user:
        raise GitHubError("GraphQL did not return the requested public user.")
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        {"date": item["date"], "count": item["contributionCount"]}
        for week in calendar["weeks"]
        for item in week["contributionDays"]
    ]
    if not days:
        raise GitHubError("GitHub returned an empty contribution calendar.")
    return {
        "days": days,
        "total": int(calendar["totalContributions"]),
    }


def save_svg(filename: str, content: str) -> None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise GitHubError(f"Generated malformed SVG {filename}: {exc}") from exc
    if not root.tag.endswith("svg") or len(content) < 100:
        raise GitHubError(f"Generated invalid or empty SVG: {filename}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / filename).write_text(content, encoding="utf-8")
    print(f"Generated assets/{filename} ({len(content)} bytes)")


def build_stats_svg(user: dict[str, Any], repos: list[dict[str, Any]], calendar: dict[str, Any]) -> str:
    stars = sum(int(repo.get("stargazers_count", 0)) for repo in repos)
    cards = [
        ("PUBLIC REPOSITORIES", len(repos), CYAN),
        ("FOLLOWERS", int(user.get("followers", 0)), PURPLE),
        ("TOTAL PUBLIC STARS", stars, PINK),
        ("CONTRIBUTIONS · 365 DAYS", calendar["total"], CYAN),
    ]
    fragments = []
    for index, (label, value, accent) in enumerate(cards):
        x, y = 24 + (index % 2) * 372, 58 + (index // 2) * 112
        fragments.append(
            f'<rect x="{x}" y="{y}" width="348" height="88" rx="13" '
            f'fill="{PANEL}" stroke="{accent}" stroke-opacity=".7"/>'
            f'<text x="{x+18}" y="{y+31}" fill="{MUTED}" font-size="12" '
            f'letter-spacing="1">{escape(label)}</text>'
            f'<text x="{x+18}" y="{y+69}" fill="{accent}" font-size="29" '
            f'font-weight="700">{value:,}</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="744" height="300" '
        'viewBox="0 0 744 300" role="img">'
        '<title>GitHub statistics</title>'
        '<desc>Public repositories, followers, public stars and yearly contributions.</desc>'
        f'<rect width="744" height="300" rx="16" fill="{BG}"/>'
        f'<text x="24" y="32" fill="{TEXT}" font-size="17" font-weight="700">'
        'GITHUB OVERVIEW</text>'
        + "".join(fragments) + '</svg>'
    )


def build_languages_svg(languages: dict[str, int]) -> str:
    ordered = sorted(languages.items(), key=lambda item: item[1], reverse=True)
    total = sum(size for _, size in ordered)
    top = ordered[:8]
    height = 122 + 43 * max(1, len(top))
    fragments = []
    if total == 0:
        fragments.append(
            f'<text x="24" y="91" fill="{MUTED}" font-size="14">'
            'No public repository language bytes are available yet.</text>'
        )
    else:
        for index, (name, size) in enumerate(top):
            y = 80 + index * 43
            percent = 100 * size / total
            accent = PALETTE[index % len(PALETTE)]
            fragments.append(
                f'<text x="24" y="{y}" fill="{TEXT}" font-size="13">{escape(name)}</text>'
                f'<rect x="166" y="{y-14}" width="470" height="11" rx="5.5" fill="#263244"/>'
                f'<rect x="166" y="{y-14}" width="{470*percent/100:.2f}" '
                f'height="11" rx="5.5" fill="{accent}"/>'
                f'<text x="710" y="{y}" text-anchor="end" fill="{accent}" '
                f'font-size="12">{percent:.1f}%</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="744" height="{height}" '
        f'viewBox="0 0 744 {height}" role="img">'
        '<title>Programming language distribution</title>'
        '<desc>Language byte counts aggregated across public repositories.</desc>'
        f'<rect width="744" height="{height}" rx="16" fill="{BG}"/>'
        f'<text x="24" y="35" fill="{CYAN}" font-size="17" font-weight="700">'
        'LANGUAGE DISTRIBUTION</text>'
        + "".join(fragments) + '</svg>'
    )


def build_activity_svg(calendar: dict[str, Any]) -> str:
    days = calendar["days"]
    first_date = datetime.strptime(days[0]["date"], "%Y-%m-%d").date()
    peak = max((item["count"] for item in days), default=0)
    levels = ["#1B2330", "#164E63", "#0E7490", PURPLE, PINK]
    cells, months = [], []
    seen_months: set[tuple[int, int]] = set()
    for item in days:
        current = datetime.strptime(item["date"], "%Y-%m-%d").date()
        offset = (current - first_date).days + first_date.weekday()
        column, row = offset // 7, offset % 7
        count = int(item["count"])
        if count == 0:
            level = 0
        else:
            level = min(4, max(1, 1 + int(3 * count / max(1, peak))))
        x, y = 24 + column * 13, 65 + row * 14
        cells.append(
            f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{levels[level]}">'
            f'<title>{escape(item["date"])}: {count} contributions</title></rect>'
        )
        key = (current.year, current.month)
        if key not in seen_months and current.day <= 7:
            seen_months.add(key)
            months.append(
                f'<text x="{24+column*13}" y="54" fill="{MUTED}" '
                f'font-size="10">{current.strftime("%b")}</text>'
            )
    week_count = (first_date.weekday() + len(days) + 6) // 7
    width = max(744, 48 + week_count * 13)
    total = int(calendar["total"])
    legend = "".join(
        f'<rect x="{574+i*17}" y="187" width="11" height="11" rx="2" fill="{color}"/>'
        for i, color in enumerate(levels)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="210" '
        f'viewBox="0 0 {width} 210" role="img">'
        '<title>Contribution activity heatmap</title>'
        '<desc>Daily contribution counts from GitHub GraphQL contribution calendar.</desc>'
        f'<rect width="{width}" height="210" rx="16" fill="{BG}"/>'
        f'<text x="24" y="29" fill="{CYAN}" font-size="17" font-weight="700">'
        'CONTRIBUTION ACTIVITY</text>'
        f'<text x="24" y="45" fill="{MUTED}" font-size="10">'
        f'{total:,} contributions in the last 365 days</text>'
        + "".join(months) + "".join(cells)
        + f'<text x="24" y="196" fill="{MUTED}" font-size="10">LESS</text>'
        + legend
        + f'<text x="{width-24}" y="196" text-anchor="end" fill="{MUTED}" '
        'font-size="10">MORE</text></svg>'
    )


def main() -> None:
    user = get_user()
    repos = get_repositories()
    languages = get_languages(repos)
    calendar = get_contribution_calendar()
    outputs = {
        "github-stats.svg": build_stats_svg(user, repos, calendar),
        "languages.svg": build_languages_svg(languages),
        "activity.svg": build_activity_svg(calendar),
    }
    # Fetch every data source successfully before publishing any chart.
    for filename, content in outputs.items():
        save_svg(filename, content)
    print(
        f"Source data validated: {len(repos)} public repositories, "
        f"{len(languages)} languages, {len(calendar['days'])} contribution days."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
