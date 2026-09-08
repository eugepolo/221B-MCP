"""Curated discovery scopes using Sherlock's site identifiers."""

from typing import Literal

Depth = Literal["light", "dev", "complete"]

# A practical selection, not a measured global popularity ranking.
LIGHT_SITES = (
    "Instagram",
    "Twitter",
    "Reddit",
    "YouTube",
    "GitHub",
    "GitLab",
    "LinkedIn",
    "Snapchat",
    "Telegram",
    "tumblr",
    "Medium",
    "Spotify",
    "SoundCloud",
    "Steam Community (User)",
    "Roblox",
    "DeviantART",
    "Behance",
    "Vimeo",
    "Kick",
    "Linktree",
)
DEV_SITES = (
    "GitHub",
    "GitLab",
    "BitBucket",
    "Codeberg",
    "SourceForge",
    "Docker Hub",
    "npm",
    "PyPi",
    "RubyGems",
    "Packagist",
    "Hugging Face",
    "Kaggle",
    "LeetCode",
    "HackerRank",
    "Codewars",
    "Codepen",
    "DEV Community",
    "Hashnode",
    "Replit.com",
    "freecodecamp",
    "HackerNews",
)


def select_sites(depth: Depth, sites: list[str] | None) -> list[str] | None:
    if depth not in {"light", "dev", "complete"}:
        raise ValueError("Depth must be light, dev or complete.")
    if sites is not None:
        return sites
    if depth == "complete":
        return None
    return list(LIGHT_SITES if depth == "light" else DEV_SITES)
