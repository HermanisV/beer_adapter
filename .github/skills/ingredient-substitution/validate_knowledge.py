#!/usr/bin/env python3
"""Validate the substitution knowledge files and report which in-stock bruve.lv items they do not cover.

Usage:
  python validate_knowledge.py                 # format check, then coverage if the bruve cache exists
  python validate_knowledge.py --cache PATH    # use a specific bruve cache (catalogue.sqlite3)
  python validate_knowledge.py --no-coverage   # format check only
Exit code 1 when the format check fails. Coverage never fails the run; it only shows where to curate next.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TIERS = ("close", "fair", "distant", "never")
REVIEW_STATES = ("draft", "reviewed")
PREFIX_BY_FILE = {"malt.md": "M", "hop.md": "H", "yeast.md": "Y", "misc.md": "X"}
# bruve product kind -> knowledge files that may cover it
FILES_BY_KIND = {
    "malt": ("malt.md",),
    "extract": ("malt.md",),
    "adjunct_grain": ("malt.md",),
    "sugar": ("malt.md", "misc.md"),
    "hop": ("hop.md",),
    "yeast": ("yeast.md",),
    "nutrient": ("misc.md",),
    "fining": ("misc.md",),
    "acid": ("misc.md",),
    "enzyme": ("misc.md", "yeast.md"),
    "water_treatment": ("misc.md",),
    "additive": ("misc.md",),
}
HERE = Path(__file__).resolve().parent
KNOWLEDGE_DIR = HERE / "knowledge"
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue", "ß": "ss"})
_MARKS = str.maketrans("", "", "™®©")


@dataclass
class Group:
    file: str
    line: int
    id: str
    members: list[str]
    tier: str
    change: str
    review: str


def norm(text: str) -> str:
    """Lowercase, fold diacritics and German umlaut spellings, reduce punctuation to single spaces."""
    text = text.translate(_MARKS).translate(_UMLAUTS)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()
    text = re.sub(r"(?<=[a-z])(?:ae|oe|ue)(?=[a-z]|\b)", lambda m: m.group(0)[0], text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def load_groups(directory: Path = KNOWLEDGE_DIR) -> tuple[list[Group], list[str]]:
    groups: list[Group] = []
    errors: list[str] = []
    for name in PREFIX_BY_FILE:
        path = directory / name
        if not path.exists():
            errors.append(f"{name}: file is missing")
            continue
        for number, raw in enumerate(path.read_text("utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = [part.strip() for part in line.split(" | ")]
            if len(fields) != 5:
                errors.append(f"{name}:{number}: expected 5 fields separated by ' | ', found {len(fields)}")
                continue
            group_id, members, tier, change, review = fields
            groups.append(
                Group(name, number, group_id, [m.strip() for m in members.split(";") if m.strip()], tier, change, review)
            )
    return groups, errors


def validate(groups: list[Group]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, Group] = {}
    for g in groups:
        where = f"{g.file}:{g.line} {g.id}"
        prefix = PREFIX_BY_FILE[g.file]
        if not re.fullmatch(rf"{prefix}-[A-Z0-9]+(?:-[A-Z0-9]+)*", g.id):
            errors.append(f"{where}: id must look like {prefix}-NAME (upper case letters, digits, hyphens)")
        if g.id in seen:
            errors.append(f"{where}: duplicate id (first used at {seen[g.id].file}:{seen[g.id].line})")
        seen[g.id] = g
        if g.tier not in TIERS:
            errors.append(f"{where}: tier {g.tier!r} must be one of {', '.join(TIERS)}")
        if g.review not in REVIEW_STATES:
            errors.append(f"{where}: review {g.review!r} must be one of {', '.join(REVIEW_STATES)}")
        if len(g.members) < 2:
            errors.append(f"{where}: needs at least 2 members")
        normalized = [norm(m) for m in g.members]
        if len(set(normalized)) != len(normalized):
            errors.append(f"{where}: repeats a member")
        if any(not n for n in normalized):
            errors.append(f"{where}: has an empty member")
        if len(g.change) < 12:
            errors.append(f"{where}: 'what changes' is too short to be useful")
    return errors


def _padded(text: str) -> str:
    return f" {norm(text)} "


def covering_groups(groups: list[Group], product_name: str, files: tuple[str, ...]) -> list[Group]:
    """Groups that mention the product. `never` groups count: knowing not to swap is knowledge too."""
    padded = _padded(product_name)
    return [g for g in groups if g.file in files and any(f" {norm(m)} " in padded for m in g.members)]


def default_cache() -> Path:
    override = os.getenv("BRUVE_MCP_CACHE_DIR")
    base = Path(override) if override else Path(os.getenv("LOCALAPPDATA") or Path.home() / ".cache") / "bruve-mcp"
    return base / "catalogue.sqlite3"


def read_products(cache: Path) -> list[tuple[str, str]]:
    connection = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
    try:
        return [(row[0], row[1]) for row in connection.execute("SELECT kind, name FROM products WHERE in_stock = 1")]
    finally:
        connection.close()


def coverage(groups: list[Group], products: list[tuple[str, str]]) -> dict[str, tuple[int, list[str]]]:
    """kind -> (covered count, uncovered names) for every kind the knowledge files can describe."""
    result: dict[str, tuple[int, list[str]]] = {}
    for kind, files in FILES_BY_KIND.items():
        names = [name for k, name in products if k == kind]
        if not names:
            continue
        uncovered = [n for n in names if not covering_groups(groups, n, files)]
        result[kind] = (len(names) - len(uncovered), uncovered)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, default=None, help="bruve cache sqlite file")
    parser.add_argument("--no-coverage", action="store_true")
    parser.add_argument("--max-list", type=int, default=40, help="how many uncovered names to print per kind")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    groups, errors = load_groups()
    errors += validate(groups)
    if errors:
        print(f"FORMAT ERRORS ({len(errors)}):")
        for error in errors:
            print(" -", error)
        return 1

    by_file: dict[str, list[Group]] = {}
    for g in groups:
        by_file.setdefault(g.file, []).append(g)
    print("knowledge format OK")
    for name, items in by_file.items():
        tiers = ", ".join(f"{t} {sum(1 for g in items if g.tier == t)}" for t in TIERS)
        reviewed = sum(1 for g in items if g.review == "reviewed")
        print(f"  {name}: {len(items)} groups ({tiers}); reviewed {reviewed}/{len(items)}")

    if args.no_coverage:
        return 0
    cache = args.cache or default_cache()
    if not cache.exists():
        print(f"\nno bruve cache at {cache}; call any bruve tool once (or bruve_refresh) to create it, then rerun for coverage")
        return 0
    products = read_products(cache)
    print(f"\ncoverage of in-stock bruve items ({len(products)} products, cache {cache.name}):")
    for kind, (covered, uncovered) in coverage(groups, products).items():
        total = covered + len(uncovered)
        print(f"  {kind:16s} {covered:3d}/{total:3d} in some group")
        for name in uncovered[: args.max_list]:
            print(f"      - {name}")
        if len(uncovered) > args.max_list:
            print(f"      ... and {len(uncovered) - args.max_list} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
