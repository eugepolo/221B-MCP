"""Implementation of search_username."""

import asyncio
import csv
import re
import tempfile
from pathlib import Path

from mcp_221b.evidence import Finding, Result
from mcp_221b.executables import sherlock_command
from mcp_221b.network import FetchError, Network
from mcp_221b.username_presets import Depth, select_sites


class SearchUsername:
    def __init__(self, network: Network):
        self.network = network
        self.sherlock_slot = asyncio.Semaphore(1)

    async def search_username(
        self, username: str, sites: list[str] | None = None, depth: Depth = "light"
    ) -> Result:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", username):
            raise ValueError(
                "Use 1–64 letters, digits, underscores, dots or hyphens; "
                "start with a letter, digit or underscore."
            )
        selected = select_sites(depth, sites)
        if selected is not None and (
            not selected
            or any(
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()!-]{0,79}", site) for site in selected
            )
        ):
            raise ValueError("Provide a nonempty list of valid Sherlock site names.")
        if selected is not None:
            selected = list(dict.fromkeys(selected))
        deadline = 600 if selected is None else max(120, len(selected) * 3)
        executable = sherlock_command()
        if not executable:
            raise ValueError(
                "Sherlock is not installed. Install this package with the [sherlock] extra."
            )
        async with self.sherlock_slot:
            with tempfile.TemporaryDirectory(prefix="221b-sherlock-") as directory:
                args = [executable, "--csv", "--print-all", "--no-color", "--timeout", "10"]
                if selected is None:
                    # Include adult sites; retain upstream false-positive exclusions.
                    args.append("--nsfw")
                for site in selected or []:
                    args.extend(["--site", site])
                args.append(username)
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=directory,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(process.wait(), timeout=deadline)
                except (TimeoutError, asyncio.CancelledError):
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                    raise
                path = Path(directory) / f"{username}.csv"
                if process.returncode != 0 or not path.is_file():
                    raise FetchError("Sherlock failed before producing a report.")
                with path.open(newline="") as report:
                    findings = parse_sherlock(report)
                returned = {f.evidence["site"].lower() for f in findings}
                for site in selected or []:
                    if site.lower() not in returned:
                        findings.append(
                            Finding(
                                source="sherlock",
                                status="unknown",
                                evidence={
                                    "site": site,
                                    "message": "Site was unsupported, excluded or not returned.",
                                },
                            )
                        )
        return Result(
            tool="search_username",
            query=username,
            findings=findings,
            notes=[
                "A matching username is only a candidate account; ownership is not established.",
                f"Scope: {'custom' if sites is not None else depth}. "
                f"Process deadline: {deadline} seconds.",
                (
                    "All available Sherlock sites requested, including adult sites; "
                    "upstream false-positive exclusions still apply."
                    if selected is None
                    else f"Requested sites: {', '.join(selected)}."
                ),
                "Sherlock coverage and detection rules vary; matches do not establish identity.",
            ],
        )


def parse_sherlock(report) -> list[Finding]:
    reader = csv.DictReader(report)
    if not {"name", "url_user", "exists", "http_status"}.issubset(reader.fieldnames or []):
        raise FetchError("Unexpected Sherlock CSV format.")
    findings = []
    for row in reader:
        raw = row["exists"].rsplit(".", 1)[-1].strip().lower()
        status = {"claimed": "found", "available": "not_found", "illegal": "unknown"}.get(
            raw, "error"
        )
        if row["http_status"] in {"401", "403", "429"}:
            status = "blocked"
        findings.append(
            Finding(
                source=row["url_user"],
                status=status,
                evidence={
                    "site": row["name"],
                    "provider_status": row["exists"],
                    "http_status": row["http_status"],
                    "identity_verified": False,
                },
            )
        )
    return findings
