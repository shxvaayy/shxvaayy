"""GitHub statistics via the GraphQL API, with caching and graceful decay.

Design goals:
- stdlib networking only (urllib) — the project's only third-party deps
  are Pillow and NumPy for the image pipeline.
- The build must never fail because of the network: every fetch group
  falls back to the last-good snapshot in generated/stats_cache.json.
- Lines-of-code scanning walks full commit histories, so results are
  cached per-repo in generated/loc_cache.json keyed by the branch head;
  daily runs only rescan repositories that received new pushes.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import Config, Stats

API_URL = "https://api.github.com/graphql"

QUERY_USER = """
query($login: String!) {
  user(login: $login) {
    id name createdAt
    followers { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {
      totalCount
    }
  }
}
"""

QUERY_REPOS = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner isFork stargazerCount
        defaultBranchRef { target { ... on Commit { oid } } }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

QUERY_CONTRIBUTIONS = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date weekday contributionCount contributionLevel }
        }
      }
    }
  }
}
"""

QUERY_HISTORY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions author { user { id } } }
          }
        }
      }
    }
  }
}
"""


class GraphQLError(Exception):
    """The API returned errors or an unusable payload."""


# What collect_stats treats as "this fetch group failed, keep the cache":
# network/API errors plus any unexpected response shape (the daily build
# must degrade, never crash, on API surprises).
FETCH_ERRORS = (GraphQLError, KeyError, TypeError, AttributeError)


def graphql(query: str, variables: dict[str, Any], token: str) -> dict[str, Any]:
    """POST one GraphQL query, retrying transient failures with backoff."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    last_error: Exception = GraphQLError("no attempts made")
    for attempt in range(3):
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "profile-terminal-builder",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            # Partial failures come back as HTTP 200 with both data and an
            # errors array (nulled-out nodes); treat them as failures so the
            # caller degrades to cache instead of tripping on the holes.
            if payload.get("data") and not payload.get("errors"):
                return payload["data"]
            raise GraphQLError(str(payload.get("errors", "empty response")))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500:
                raise GraphQLError(f"HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2 ** (attempt + 1))
    raise GraphQLError(str(last_error))


def fetch_user(username: str, token: str) -> dict[str, Any]:
    """id, name, createdAt, follower and contributed-repo counts."""
    return graphql(QUERY_USER, {"login": username}, token)["user"]


def fetch_repos(username: str, token: str) -> tuple[int, list[dict[str, Any]]]:
    """(total repo count, [{name, is_fork, stars, head_oid, languages}, ...])."""
    repos: list[dict[str, Any]] = []
    cursor: str | None = None
    total = 0
    while True:
        data = graphql(QUERY_REPOS, {"login": username, "cursor": cursor}, token)
        block = data["user"]["repositories"]
        total = block["totalCount"]
        for node in block["nodes"]:
            if not node:  # a resolver hiccup can null individual entries
                continue
            branch = node.get("defaultBranchRef") or {}
            target = branch.get("target") or {}
            edges = (node.get("languages") or {}).get("edges") or []
            repos.append(
                {
                    "name": node["nameWithOwner"],
                    "is_fork": node["isFork"],
                    "stars": node["stargazerCount"],
                    "head_oid": target.get("oid"),
                    "languages": {e["node"]["name"]: e["size"] for e in edges},
                }
            )
        if not block["pageInfo"]["hasNextPage"]:
            return total, repos
        cursor = block["pageInfo"]["endCursor"]


def fetch_contributions(username: str, token: str) -> tuple[int, list[dict[str, Any]]]:
    """(contributions over the last year, calendar weeks), as on the profile.

    The calendar total is exactly the number GitHub shows on the profile;
    private activity is included when the token (or the user's "private
    contributions" profile setting) allows it. Do NOT add
    restrictedContributionsCount on top — that double-counts. The weeks
    carry GitHub's own per-day quartile bucketing for the heatmap panel.
    """
    data = graphql(QUERY_CONTRIBUTIONS, {"login": username}, token)
    calendar = data["user"]["contributionsCollection"]["contributionCalendar"]
    return calendar["totalContributions"], calendar["weeks"]


def aggregate_languages(
    repos: list[dict[str, Any]], loc_config: dict[str, Any]
) -> dict[str, int]:
    """Byte totals per language, honoring the same exclusions as LOC."""
    include_forks = bool(loc_config.get("include_forks", False))
    excluded = set(loc_config.get("exclude_repos", []))
    totals: dict[str, int] = {}
    for repo in repos:
        if repo["name"] in excluded or (repo["is_fork"] and not include_forks):
            continue
        for name, size in repo.get("languages", {}).items():
            totals[name] = totals.get(name, 0) + size
    return totals


def scan_repo_loc(
    repo_name: str, user_id: str, token: str, max_pages: int
) -> tuple[int, int, int]:
    """(my commits, additions, deletions) on a repo's default branch."""
    owner, name = repo_name.split("/", 1)
    commits = added = deleted = 0
    cursor: str | None = None
    for _ in range(max_pages):
        data = graphql(
            QUERY_HISTORY, {"owner": owner, "name": name, "cursor": cursor}, token
        )
        branch = (data.get("repository") or {}).get("defaultBranchRef") or {}
        history = (branch.get("target") or {}).get("history")
        if history is None:
            break
        for node in history["nodes"]:
            author = (node.get("author") or {}).get("user") or {}
            if author.get("id") == user_id:
                commits += 1
                added += node["additions"]
                deleted += node["deletions"]
        if not history["pageInfo"]["hasNextPage"]:
            break
        cursor = history["pageInfo"]["endCursor"]
    else:
        print(f"loc: {repo_name} truncated at {max_pages} pages", file=sys.stderr)
    return commits, added, deleted


def refresh_loc_cache(
    repos: list[dict[str, Any]],
    user_id: str,
    token: str,
    cache: dict[str, Any],
    loc_config: dict[str, Any],
) -> dict[str, Any]:
    """Rescan only repositories whose head commit moved since last run."""
    include_forks = bool(loc_config.get("include_forks", False))
    excluded = set(loc_config.get("exclude_repos", []))
    max_pages = int(loc_config.get("max_pages_per_repo", 30))
    entries: dict[str, Any] = {}
    for repo in repos:
        name, head = repo["name"], repo["head_oid"]
        if head is None or name in excluded or (repo["is_fork"] and not include_forks):
            continue
        cached = cache.get(name)
        if cached and cached.get("head_oid") == head:
            entries[name] = cached
            continue
        commits, added, deleted = scan_repo_loc(name, user_id, token, max_pages)
        entries[name] = {
            "head_oid": head,
            "commits": commits,
            "additions": added,
            "deletions": deleted,
        }
        print(f"loc: scanned {name} (+{added}, -{deleted})", file=sys.stderr)
    return entries


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_panel_data(generated_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(calendar weeks, language byte totals) from the panels cache.

    The cache is written by collect_stats() and deliberately contains no
    repository names, so it is always safe to commit.
    """
    cache = _read_json(generated_dir / "panels_cache.json")
    return cache.get("calendar", []), cache.get("languages", {})


def load_loc_cache(generated_dir: Path) -> dict[str, Any]:
    """Per-repo {commits, additions, deletions} from the LOC cache."""
    return _read_json(generated_dir / "loc_cache.json").get("repos", {})


def _stats_from_cache(cache: dict[str, Any], config: Config) -> Stats:
    known = {f for f in Stats.__dataclass_fields__}
    stats = Stats(**{k: v for k, v in cache.items() if k in known})
    stats.username = config.username
    stats.name = stats.name or config.display_name
    stats.partial = True
    return stats


def collect_stats(
    config: Config, token: str | None, generated_dir: Path, offline: bool = False
) -> Stats:
    """Gather all dynamic numbers; degrade to cached values, never raise."""
    stats_cache_path = generated_dir / "stats_cache.json"
    loc_cache_path = generated_dir / "loc_cache.json"
    snapshot = _read_json(stats_cache_path)

    if offline or not token:
        if not offline:
            print("stats: no token available, using cached values", file=sys.stderr)
        return _stats_from_cache(snapshot, config)

    stats = _stats_from_cache(snapshot, config)
    stats.partial = False
    user_id = ""
    panels_path = generated_dir / "panels_cache.json"
    panels = _read_json(panels_path)

    try:
        user = fetch_user(config.username, token)
        user_id = user["id"]
        stats.name = user.get("name") or config.display_name
        stats.created_at = user["createdAt"]
        stats.followers = user["followers"]["totalCount"]
        stats.contributed = user["repositoriesContributedTo"]["totalCount"]
    except FETCH_ERRORS as exc:
        print(f"stats: user query failed ({exc}), keeping cache", file=sys.stderr)
        stats.partial = True

    repos: list[dict[str, Any]] = []
    try:
        stats.repos, repos = fetch_repos(config.username, token)
        stats.stars = sum(r["stars"] for r in repos)
        panels["languages"] = aggregate_languages(repos, config.loc)
    except FETCH_ERRORS as exc:
        print(f"stats: repo query failed ({exc}), keeping cache", file=sys.stderr)
        stats.partial = True

    try:
        stats.contributions_year, panels["calendar"] = fetch_contributions(
            config.username, token
        )
    except FETCH_ERRORS as exc:
        print(f"stats: contribution query failed ({exc}), keeping cache", file=sys.stderr)
        stats.partial = True

    panels["version"] = 1
    panels_path.write_text(json.dumps(panels, indent=2) + "\n", encoding="utf-8")

    loc_cache = _read_json(loc_cache_path).get("repos", {})
    if repos and user_id:
        try:
            loc_cache = refresh_loc_cache(repos, user_id, token, loc_cache, config.loc)
            loc_cache_path.write_text(
                json.dumps({"version": 1, "repos": loc_cache}, indent=2) + "\n",
                encoding="utf-8",
            )
        except FETCH_ERRORS as exc:
            print(f"stats: loc scan failed ({exc}), keeping cache", file=sys.stderr)
            stats.partial = True
    if loc_cache:
        stats.commits = sum(e["commits"] for e in loc_cache.values())
        stats.loc_added = sum(e["additions"] for e in loc_cache.values())
        stats.loc_deleted = sum(e["deletions"] for e in loc_cache.values())

    stats.fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stats_cache_path.write_text(
        json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8"
    )
    return stats
