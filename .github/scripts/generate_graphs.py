#!/usr/bin/env python3
"""Generate trustworthy profile analytics SVGs from GitHub public data.

Repository, follower, star and language data use GitHub REST API.
The contribution calendar is read from GitHub's public profile markup because
the REST API does not expose daily contribution counts. If that markup changes
or is unavailable, this script fails rather than fabricating a heatmap.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

USERNAME = os.environ.get("GITHUB_USERNAME", "abidhasan789diu-ship-it")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
API = "https://api.github.com"
OUT = Path("assets")
BG, PANEL, TEXT, MUTED = "#0D1117", "#161B22", "#E6EDF3", "#9AA7B5"
CYAN, PURPLE, PINK = "#00F5FF", "#8B5CF6", "#FF00FF"
PALETTE = [CYAN, PURPLE, PINK, "#38BDF8", "#A78BFA", "#F472B6", "#22D3EE", "#C084FC"]


class GitHubError(RuntimeError):
    pass


def request_json(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{USERNAME}-profile-analytics",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(4):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (403, 429) and attempt < 3:
                retry_after = exc.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                time.sleep(max(1, min(wait, 60)))
                continue
            raise GitHubError(f"GitHub API returned {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise GitHubError(f"Network request failed: {exc}") from exc
            time.sleep(2 ** attempt)
    raise GitHubError(f"Could not retrieve {url}")


def get_user() -> dict[str, Any]:
    return request_json(f"{API}/users/{urllib.parse.quote(USERNAME)}")


def get_repositories() -> list[dict[str, Any]]:
    all_repos: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request_json(
            f"{API}/users/{urllib.parse.quote(USERNAME)}/repos"
            f"?type=owner&sort=updated&per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise GitHubError("Unexpected response while listing repositories.")
        all_repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [
        item for item in all_repos
        if not item.get("fork") and not item.get("private") and not item.get("archived")
    ]


def get_languages(repositories: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for repository in repositories:
        url = repository.get("languages_url")
        if not url:
            continue
        result = request_json(url)
        if not isinstance(result, dict):
            raise GitHubError(f"Invalid languages payload for {repository.get('full_name')}")
        for language, byte_count in result.items():
            if isinstance(byte_count, int) and byte_count >= 0:
                totals[language] += byte_count
    return dict(totals)


def get_contribution_days() -> list[dict[str, Any]]:
    # GitHub does not provide daily contributions in its public REST API.
    # This public profile page is a best-effort source; never invent values.
    url = f"https://github.com/users/{urllib.parse.quote(USERNAME)}/contributions"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 profile-analytics-bot",
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise GitHubError(f"Unable to read GitHub public contributions page: {exc}") from exc

    pattern = re.compile(
        r'<td[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*data-count="(\d+)"'
        r'|<td[^>]*data-count="(\d+)"[^>]*data-date="(\d{4}-\d{2}-\d{2})"'
    )
    by_date: dict[str, int] = {}
    for match in pattern.finditer(html):
        if match.group(1):
            day, count = match.group(1), int(match.group(2))
        else:
            count, day = int(match.group(3)), match.group(4)
        by_date[day] = count

    if len(by_date) < 300:
        raise GitHubError(
            f"Contribution page format was unavailable/incomplete ({len(by_date)} days). "
            "No contribution SVG was generated."
        )

    end = date.today()
    start = end - timedelta(days=364)
    days = [
        {"date": key, "count": value}
        for key, value in sorted(by_date.items())
        if start.isoformat() <= key <= end.isoformat()
    ]
    if len(days) < 300:
        raise GitHubError(f"Only {len(days)} contribution days were returned.")
    return days


def save_svg(filename: str, content: str) -> None:
    if len(content) < 100:
        raise GitHubError(f"Refusing to write empty SVG: {filename}")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise GitHubError(f"Generated malformed SVG {filename}: {exc}") from exc
    if not root.tag.endswith("svg"):
        raise GitHubError(f"Invalid SVG root element in {filename}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / filename).write_text(content, encoding="utf-8")
    print(f"Generated assets/{filename} ({len(content)} bytes)")


def create_stats_svg(user: dict[str, Any], repositories: list[dict[str, Any]], contribution_days: list[dict[str, Any]]) -> str:
    stars = sum(int(item.get("stargazers_count", 0)) for item in repositories)
    values = [
        ("PUBLIC REPOSITORIES", len(repositories), CYAN),
        ("FOLLOWERS", int(user.get("followers", 0)), PURPLE),
        ("TOTAL PUBLIC STARS", stars, PINK),
        ("CONTRIBUTIONS · 365 DAYS", sum(d["count"] for d in contribution_days), CYAN),
    ]
    cards = []
    for index, (label, value, accent) in enumerate(values):
        x, y = 24 + (index % 2) * 372, 58 + (index // 2) * 112
        cards.append(
            f'<rect x="{x}" y="{y}" width="348" height="88" rx="13" fill="{PANEL}" stroke="{accent}" stroke-opacity=".7"/>'
            f'<text x="{x+18}" y="{y+31}" fill="{MUTED}" font-size="12" letter-spacing="1">{escape(label)}</text>'
            f'<text x="{x+18}" y="{y+69}" fill="{accent}" font-size="29" font-weight="700">{value:,}</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="744" height="300" viewBox="0 0 744 300" role="img">'
        '<title>GitHub statistics</title><desc>Public repositories, followers, public stars and yearly contributions.</desc>'
        f'<rect width="744" height="300" rx="16" fill="{BG}"/>'
        f'<text x="24" y="32" fill="{TEXT}" font-size="17" font-weight="700">GITHUB OVERVIEW</text>'
        + "".join(cards) + "</svg>"
    )


def create_languages_svg(languages: dict[str, int]) -> str:
    ordered = sorted(languages.items(), key=lambda item: item[1], reverse=True)
    total = sum(size for _, size in ordered)
    if total <= 0:
        raise GitHubError("No public language bytes available; refusing to generate empty chart.")
    top = ordered[:8]
    height = 82 + 43 * len(top) + 20
    rows = []
    for index, (name, size) in enumerate(top):
        y = 80 + index * 43
        pct = 100 * size / total
        accent = PALETTE[index % len(PALETTE)]
        rows.append(
            f'<text x="24" y="{y}" fill="{TEXT}" font-size="13">{escape(name)}</text>'
            f'<rect x="166" y="{y-14}" width="470" height="11" rx="5.5" fill="#263244"/>'
            f'<rect x="166" y="{y-14}" width="{470*pct/100:.2f}" height="11" rx="5.5" fill="{accent}"/>'
            f'<text x="710" y="{y}" text-anchor="end" fill="{accent}" font-size="12">{pct:.1f}%</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="744" height="{height}" viewBox="0 0 744 {height}" role="img">'
        '<title>Programming language distribution</title><desc>Language byte counts across public repositories.</desc>'
        f'<rect width="744" height="{height}" rx="16" fill="{BG}"/>'
        f'<text x="24" y="35" fill="{CYAN}" font-size="17" font-weight="700">LANGUAGE DISTRIBUTION</text>'
        + "".join(rows) + "</svg>"
    )


def create_activity_svg(days: list[dict[str, Any]]) -> str:
    start = date.fromisoformat(days[0]["date"])
    cells, labels = [], []
    seen_months: set[tuple[int, int]] = set()
    peak = max((item["count"] for item in days), default=0)
    for item in days:
        current = date.fromisoformat(item["date"])
        offset = (current - start).days + start.weekday()
        col, row = offset // 7, offset % 7
        count = item["count"]
        intensity = 0 if count == 0 else min(4, 1 + int(4 * count / max(1, peak)))
        palette = ["#1B2330", "#164E63", "#0E7490", PURPLE, PINK]
        x, y = 24 + col * 13, 65 + row * 14
        cells.append(
            f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{palette[intensity]}">'
            f'<title>{escape(item["date"])}: {count} contributions</title></rect>'
        )
        month = (current.year, current.month)
        if month not in seen_months and current.day <= 7:
            seen_months.add(month)
            labels.append(
                f'<text x="{24+col*13}" y="54" fill="{MUTED}" font-size="10">{current.strftime("%b")}</text>'
            )
    weeks = (start.weekday() + len(days) + 6) // 7
    width = max(744, 48 + weeks * 13)
    total = sum(item["count"] for item in days)
    legend = "".join(
        f'<rect x="{574+i*17}" y="187" width="11" height="11" rx="2" fill="{color}"/>'
        for i, color in enumerate(["#1B2330", "#164E63", "#0E7490", PURPLE, PINK])
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="210" viewBox="0 0 {width} 210" role="img">'
        '<title>Contribution activity heatmap</title><desc>Daily contribution counts from GitHub public profile data.</desc>'
        f'<rect width="{width}" height="210" rx="16" fill="{BG}"/>'
        f'<text x="24" y="29" fill="{CYAN}" font-size="17" font-weight="700">CONTRIBUTION ACTIVITY</text>'
        f'<text x="24" y="45" fill="{MUTED}" font-size="10">{total:,} contributions in the last 365 days</text>'
        + "".join(labels) + "".join(cells)
        + f'<text x="24" y="196" fill="{MUTED}" font-size="10">LESS</text>{legend}'
        + f'<text x="{width-24}" y="196" text-anchor="end" fill="{MUTED}" font-size="10">MORE</text></svg>'
    )


def main() -> None:
    user = get_user()
    if user.get("login", "").lower() != USERNAME.lower():
        raise GitHubError("The GitHub API returned a different account.")
    repositories = get_repositories()
    languages = get_languages(repositories)
    contribution_days = get_contribution_days()

    # Create every output in memory first; only write after all sources succeeded.
    outputs = {
        "github-stats.svg": create_stats_svg(user, repositories, contribution_days),
        "languages.svg": create_languages_svg(languages),
        "activity.svg": create_activity_svg(contribution_days),
    }
    for filename, content in outputs.items():
        save_svg(filename, content)
    print(
        f"Source data: {len(repositories)} public repositories; "
        f"{len(languages)} languages; {len(contribution_days)} contribution days."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
