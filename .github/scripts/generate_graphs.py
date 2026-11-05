
import os
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape

USERNAME = "abidhasan789diu-ship-it"
TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com/graphql"

def github_query():
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        followers { totalCount }
        repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
          totalCount
          nodes {
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node { name color }
              }
            }
          }
        }
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """

    payload = {
        "query": query,
        "variables": {
            "login": USERNAME,
            "from": start.isoformat(),
            "to": end.isoformat()
        }
    }

    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": USERNAME
        }
    )

    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read())

    if "errors" in result:
        raise RuntimeError(result["errors"])

    return result["data"]["user"]


def save_svg(filename, content):
    os.makedirs("assets", exist_ok=True)
    with open(f"assets/{filename}", "w", encoding="utf-8") as file:
        file.write(content)


def make_stats(user):
    repos = user["repositories"]
    contributions = user["contributionsCollection"]["contributionCalendar"]

    total_stars = sum(
        repo["stargazerCount"] for repo in repos["nodes"]
    )

    cards = [
        ("PUBLIC REPOSITORIES", repos["totalCount"], "#00F5FF"),
        ("FOLLOWERS", user["followers"]["totalCount"], "#A855F7"),
        ("TOTAL STARS", total_stars, "#FF00FF"),
        ("CONTRIBUTIONS", contributions["totalContributions"], "#00F5FF")
    ]

    items = ""
    for i, (label, value, color) in enumerate(cards):
        x = 20 + (i % 2) * 370
        y = 25 + (i // 2) * 110
        items += f"""
        <rect x="{x}" y="{y}" width="345" height="85"
          rx="12" fill="#161B22" stroke="{color}" stroke-width="1.5"/>
        <text x="{x+18}" y="{y+30}" fill="#AAB7C4"
          font-size="13">{label}</text>
        <text x="{x+18}" y="{y+67}" fill="{color}"
          font-size="30" font-weight="bold">{value}</text>
        """

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
      width="740" height="255" viewBox="0 0 740 255">
      <rect width="100%" height="100%" rx="15" fill="#0D1117"/>
      <text x="20" y="16" fill="#FFFFFF" font-size="11">
        GITHUB ANALYTICS · LAST 365 DAYS
      </text>
      {items}
    </svg>"""

    save_svg("github-stats.svg", svg)


def make_languages(user):
    languages = {}

    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            languages[name] = languages.get(name, 0) + edge["size"]

    sorted_langs = sorted(
        languages.items(), key=lambda item: item[1], reverse=True
    )[:8]

    total = sum(size for _, size in sorted_langs) or 1
    items = ""

    for i, (name, size) in enumerate(sorted_langs):
        y = 55 + i * 43
        percent = size / total * 100
        width = percent * 4.7
        color = ["#00F5FF", "#A855F7", "#FF00FF",
                 "#22C55E", "#F59E0B", "#3B82F6",
                 "#EC4899", "#14B8A6"][i]

        items += f"""
        <text x="20" y="{y}" fill="#FFFFFF" font-size="14">
          {escape(name)}
        </text>
        <rect x="150" y="{y-13}" width="470" height="12"
          rx="6" fill="#263244"/>
        <rect x="150" y="{y-13}" width="{width:.1f}" height="12"
          rx="6" fill="{color}"/>
        <text x="640" y="{y}" fill="{color}" font-size="13">
          {percent:.1f}%
        </text>
        """

    if not sorted_langs:
        items = '<text x="20" y="65" fill="#FFFFFF">No public language data yet</text>'

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
      width="740" height="420" viewBox="0 0 740 420">
      <rect width="100%" height="100%" rx="15" fill="#0D1117"/>
      <text x="20" y="30" fill="#00F5FF" font-size="19"
        font-weight="bold">PROGRAMMING LANGUAGE DISTRIBUTION</text>
      {items}
    </svg>"""

    save_svg("languages.svg", svg)


def make_activity(user):
    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks = calendar["weeks"]

    colors = ["#161B22", "#123B46", "#087E8B", "#00B8D9", "#00F5FF"]
    cells = ""

    for week_index, week in enumerate(weeks):
        for day_index, day in enumerate(week["contributionDays"]):
            count = day["contributionCount"]
            level = 0 if count == 0 else min(4, 1 + count // 3)
            x = 20 + week_index * 13
            y = 55 + day_index * 17
            cells += f"""
            <rect x="{x}" y="{y}" width="10" height="10"
              rx="2" fill="{colors[level]}">
              <title>{day['date']}: {count} contributions</title>
            </rect>
            """

    total = calendar["totalContributions"]

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
      width="760" height="205" viewBox="0 0 760 205">
      <rect width="100%" height="100%" rx="15" fill="#0D1117"/>
      <text x="20" y="28" fill="#00F5FF" font-size="18"
        font-weight="bold">CONTRIBUTION ACTIVITY</text>
      <text x="20" y="45" fill="#AAB7C4" font-size="11">
        {total} contributions in the last year
      </text>
      {cells}
      <text x="20" y="190" fill="#AAB7C4" font-size="11">
        LESS
      </text>
      <text x="700" y="190" fill="#AAB7C4" font-size="11">
        MORE
      </text>
    </svg>"""

    save_svg("activity.svg", svg)


def main():
    user = github_query()
    make_stats(user)
    make_languages(user)
    make_activity(user)
    print("All GitHub charts generated successfully!")


if __name__ == "__main__":
    main()
