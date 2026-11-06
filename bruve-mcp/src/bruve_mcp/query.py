"""Turn free-text ingredient names into FTS5 match expressions, with a small LV/EN synonym table.

All words are folded (diacritics removed, German ae/oe/ue collapsed) exactly like indexed text.
Extend SYNONYM_GROUPS when a real ingredient name fails to match; groups are plain word sets.
"""

from __future__ import annotations

import re

from .parse.common import fold

SYNONYM_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(fold(w) for w in group)
    for group in (
        {"hop", "hops", "apini", "apinu", "apins"},
        {"yeast", "raugs", "raugi", "rauga"},
        {"malt", "iesals", "iesali", "iesala"},
        {"wheat", "kviesu", "kviesi", "weizen"},
        {"pilsner", "pilsen", "pils", "pilsener"},
        {"munich", "minhene", "minhenes", "muenchen"},
        {"vienna", "vine", "wiener"},
        {"caramel", "karamele", "crystal", "cara", "karamelizets"},
        {"chocolate", "sokolade"},
        {"roasted", "grauzdets", "grauzdeti"},
        {"barley", "miezu", "mieziem", "miezi"},
        {"rye", "rudzu", "rudzi"},
        {"oat", "oats", "auzu", "auzas"},
        {"flaked", "flakes", "flake", "parslas", "parsloti"},
        {"amber", "dzintara"},
        {"smoked", "smoke", "kupinats", "kupinata"},
        {"acidulated", "sauer", "skabais"},
        {"dextrin", "dekstrins", "carapils", "carafoam"},
        {"biscuit", "biskvits"},
        {"extract", "ekstrakts"},
        {"dry", "sausais", "sauss"},
        {"liquid", "skidrais", "skidrie"},
        {"wine", "vina", "vins"},
        {"cider", "sidra", "sidrs"},
        {"mead", "medus", "medalus"},
        {"nutrient", "nutrients", "baribas", "barib"},
        {"sugar", "cukurs", "cukuri"},
        {"dextrose", "glikoze", "glucose"},
        {"lactose", "laktoze"},
        {"oak", "ozola", "ozols"},
        {"fining", "clarifier", "dzidrinasana", "dzidrinatajs"},
        {"water", "udens"},
        {"gypsum", "gipsis"},
        {"bacteria", "baktrijas", "lactobacillus"},
        {"orange", "apelsinu", "apelsins"},
        {"peel", "miziņas", "mizinas"},
    )
)
_GROUP_BY_WORD: dict[str, frozenset[str]] = {word: group for group in SYNONYM_GROUPS for word in group}
STOP_WORDS = frozenset({"the", "of", "and", "a", "an", "with", "for", "pellet", "pellets"})
_WORD = re.compile(r"[a-z0-9]+")
MAX_WORDS = 8


def _prefix(token: str) -> str:
    return f'"{token}"*' if len(token) >= 3 else f'"{token}"'


def _word_clause(word: str) -> str | None:
    parts = _WORD.findall(word)
    if not parts:
        return None
    if len(parts) > 1:
        # 'us-05' or 'w-34/70': match the sequence, not loose parts.
        return '"' + " ".join(parts) + '"'
    token = parts[0]
    if token in STOP_WORDS:
        return None
    group = _GROUP_BY_WORD.get(token)
    if group:
        return "(" + " OR ".join(_prefix(t) for t in sorted(group)) + ")"
    return _prefix(token)


def build_match(query: str, *, loose: bool = False) -> str | None:
    """Return an FTS5 expression (all words must match; `loose` = any word may match) or None."""
    clauses = []
    for word in fold(query).split()[:MAX_WORDS]:
        clause = _word_clause(word)
        if clause:
            clauses.append(clause)
    if not clauses:
        return None
    return (" OR " if loose else " AND ").join(clauses)
