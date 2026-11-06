"""Pure recipe-derivation logic: clone a Brewfather recipe and apply whitelisted ingredient edits.

The model never composes a full recipe. It names a base recipe and a short list of edits; this module
clones the original JSON, applies the edits against field whitelists with range checks, and strips
everything the server manages or recalculates. No network access happens here.
"""

from __future__ import annotations

import copy
import math
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["fermentable", "hop", "yeast", "misc"]
Op = Literal["replace", "resize", "remove", "add"]

LIST_KEY: dict[str, str] = {"fermentable": "fermentables", "hop": "hops", "yeast": "yeasts", "misc": "miscs"}
UNIT: dict[str, str] = {"fermentable": "kg", "hop": "g", "yeast": "pkg", "misc": ""}
AMOUNT_DECIMALS = {"fermentable": 3, "hop": 1, "yeast": 2, "misc": 2}

MAX_EDITS = 30
MAX_STRING = 120
MAX_NOTES_APPEND = 4000
MAX_AMOUNT = {"fermentable": 100.0, "hop": 5000.0, "yeast": 100.0, "misc": 100000.0}

# name -> (type, minimum, maximum). Strings use (str, None, None).
_S = (str, None, None)
SETTABLE: dict[str, dict[str, tuple]] = {
    "fermentable": {
        "name": _S, "supplier": _S, "origin": _S, "type": _S, "grainCategory": _S,
        "color": (float, 0, 1000), "potential": (float, 1.0, 1.1), "moisture": (float, 0, 100),
        "protein": (float, 0, 100), "diastaticPower": (float, 0, 500), "attenuation": (float, 0, 100),
        "notFermentable": (bool, None, None),
        "use": _S, "time": (float, 0, 100000), "timeUnit": _S,
    },
    "hop": {
        "name": _S, "origin": _S, "type": _S,
        "alpha": (float, 0, 40), "beta": (float, 0, 20), "year": (float, 1990, 2100), "hsi": (float, 0, 100),
        "use": _S, "usage": _S, "time": (float, 0, 365), "timeUnit": _S, "temp": (float, 0, 100),
    },
    "yeast": {
        "name": _S, "laboratory": _S, "productId": _S, "type": _S, "form": _S, "flocculation": _S,
        "attenuation": (float, 0, 100), "minTemp": (float, -10, 60), "maxTemp": (float, -10, 60),
        "fermentsAll": (bool, None, None), "unit": _S,
    },
    "misc": {
        "name": _S, "type": _S, "use": _S, "unit": _S,
        "time": (float, 0, 100000), "timeIsDays": (bool, None, None),
    },
}
# Fields that describe how the ingredient is used in this recipe, so they survive a replacement.
ROLE_FIELDS: dict[str, tuple[str, ...]] = {
    "fermentable": ("use", "time", "timeUnit"),
    "hop": ("use", "time", "timeUnit", "temp", "usage"),
    "yeast": ("unit",),
    "misc": ("use", "time", "timeIsDays", "unit"),
}
# Fields kept from the replaced ingredient when the replacement does not say otherwise.
INHERIT_FIELDS: dict[str, tuple[str, ...]] = {
    "fermentable": ("type",),
    "hop": ("type",),
    "yeast": ("type", "form"),
    "misc": ("type",),
}
# Recalculated by Brewfather; sent back stale they would mislead, so they are removed from the clone.
ROOT_DERIVED = frozenset(
    {
        "og", "fg", "fgEstimated", "abv", "ibu", "color", "attenuation", "buGuRatio", "rbRatio",
        "preBoilGravity", "postBoilGravity", "firstWortGravity", "totalGravity", "extraGravity", "ogPlato",
        "fermentableIbu", "hopsTotalAmount", "fermentablesTotalAmount", "diastaticPower",
        "avgWeightedHopstandTemp", "sumDryHopPerLiter", "yeastToleranceExceededBy", "styleConformity", "nutrition",
    }
)
ROOT_INSTANCE_BOUND = frozenset(
    {"createdAt", "updatedAt", "data", "img", "img_url", "thumb", "searchTags", "folderRefs", "path", "updatedBy"}
)
INGREDIENT_DERIVED: dict[str, frozenset[str]] = {
    "fermentable": frozenset({"percentage", "potentialPercentage", "ibuPerAmount"}),
    "hop": frozenset({"ibu"}),
    "yeast": frozenset(),
    "misc": frozenset({"amountPerL"}),
}
INVENTORY_ONLY = frozenset({"inventory", "hidden", "costPerAmount", "userNotes", "notes"})
BITTERING_MIN_TIME = 15


class RecipeEdit(BaseModel):
    op: Op = Field(description="replace | resize | remove | add")
    kind: Kind = Field(description="fermentable | hop | yeast | misc")
    target: str | None = Field(default=None, description="Ingredient name, or #n (1-based position in the original list)")
    amount: float | None = Field(default=None, description="Absolute amount (kg, g, pkg or misc unit); single target only")
    scale: float | None = Field(default=None, description="Multiply the current amount")
    inventory_id: str | None = Field(default=None, description="Brewfather inventory item id to copy specs from")
    fields: dict[str, str | float | bool | None] | None = Field(
        default=None, description="Spec overrides, e.g. name, supplier, color (SRM), alpha, laboratory"
    )
    keep_ibu: bool = Field(default=True, description="Hop replace: rescale a bittering hop's grams by the alpha ratio")


@dataclass
class EditOutcome:
    body: dict[str, Any]
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: int = 0
    inventory_ids: list[tuple[str, str]] = field(default_factory=list)


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def needed_inventory(edits: list[RecipeEdit]) -> list[tuple[str, str]]:
    """(kind, inventory id) pairs the edits need fetched before apply_edits can run."""
    seen: list[tuple[str, str]] = []
    for edit in edits:
        if edit.inventory_id and (edit.kind, edit.inventory_id) not in seen:
            seen.append((edit.kind, edit.inventory_id))
    return seen


def _check_value(kind: str, key: str, value: Any) -> Any:
    spec = SETTABLE[kind].get(key)
    if spec is None:
        allowed = ", ".join(sorted(SETTABLE[kind]))
        raise ValueError(f"{kind} field {key!r} cannot be set; allowed: {allowed}")
    if value is None:
        return None
    expected, low, high = spec
    if expected is str:
        text = " ".join(str(value).split())
        if len(text) > MAX_STRING:
            raise ValueError(f"{kind}.{key} is longer than {MAX_STRING} characters")
        return text
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{kind}.{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{kind}.{key} must be a finite number")
    if not (low <= value <= high):
        raise ValueError(f"{kind}.{key} must be between {low} and {high}")
    return float(value)


def _check_amount(kind: str, value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0 or value > MAX_AMOUNT[kind]:
        raise ValueError(f"{name} must be between 0 and {MAX_AMOUNT[kind]:g}")
    return round(float(value), AMOUNT_DECIMALS[kind])


def _resolve(items: list[dict | None], kind: str, target: str | None) -> list[int]:
    if not target or not target.strip():
        raise ValueError(f"{kind} edit needs a target (name or #n)")
    target = target.strip()
    live = [(i, it) for i, it in enumerate(items) if it is not None]
    if re.fullmatch(r"#\d{1,3}", target):
        index = int(target[1:]) - 1
        if not (0 <= index < len(items)) or items[index] is None:
            raise ValueError(f"{kind} {target} does not exist (the list has {len(live)} items)")
        return [index]
    wanted = _norm(target)
    exact = [i for i, it in live if _norm(it.get("name")) == wanted]
    if exact:
        return exact
    partial = [i for i, it in live if wanted in _norm(it.get("name"))]
    if len(partial) == 1:
        return partial
    names = "; ".join(f"#{i + 1} {it.get('name')}" for i, it in live)
    problem = "matches several" if partial else "matches none"
    raise ValueError(f"{kind} target {target!r} {problem}. Items: {names}")


def _new_id() -> str:
    return "default-" + secrets.token_hex(4)


def _fmt_amount(kind: str, item: dict) -> str:
    amount = item.get("amount")
    if amount is None:
        return "?"
    unit = UNIT[kind] or str(item.get("unit") or "")
    return f"{amount:g}{unit}"


def _describe(kind: str, item: dict) -> str:
    parts = [str(item.get("name") or "?"), _fmt_amount(kind, item)]
    if kind == "hop":
        extras = [f"AA{item['alpha']:g}" if item.get("alpha") is not None else None, item.get("use"),
                  f"{item['time']:g}'" if item.get("time") is not None else None]
        parts.extend(str(e) for e in extras if e)
    elif kind == "fermentable" and item.get("color") is not None:
        parts.append(f"{item['color']:.1f}SRM")
    return " ".join(parts)


def _build_replacement(kind: str, old: dict, edit: RecipeEdit, inventory: dict[tuple[str, str], dict]) -> dict:
    new: dict[str, Any] = {}
    for key in INHERIT_FIELDS[kind]:
        if old.get(key) is not None:
            new[key] = old[key]
    for key in ROLE_FIELDS[kind]:
        if key in old:
            new[key] = old[key]
    new["amount"] = old.get("amount")

    if edit.inventory_id:
        source = inventory.get((kind, edit.inventory_id))
        if source is None:
            raise ValueError(f"inventory item {edit.inventory_id!r} was not found")
        for key in SETTABLE[kind]:
            if key in ROLE_FIELDS[kind] and key in old:
                continue
            if key in source and source[key] is not None and key not in INVENTORY_ONLY:
                new[key] = source[key]
        new["_id"] = source.get("_id") or _new_id()
    else:
        new["_id"] = _new_id()

    for key, value in (edit.fields or {}).items():
        new[key] = _check_value(kind, key, value)
    if not new.get("name"):
        raise ValueError(f"replacement {kind} needs a name (fields.name or inventory_id)")
    return new


def _build_new(kind: str, edit: RecipeEdit, inventory: dict[tuple[str, str], dict]) -> dict:
    new: dict[str, Any] = {}
    if edit.inventory_id:
        source = inventory.get((kind, edit.inventory_id))
        if source is None:
            raise ValueError(f"inventory item {edit.inventory_id!r} was not found")
        for key in SETTABLE[kind]:
            if key in source and source[key] is not None and key not in INVENTORY_ONLY:
                new[key] = source[key]
        new["_id"] = source.get("_id") or _new_id()
    else:
        new["_id"] = _new_id()
    for key, value in (edit.fields or {}).items():
        new[key] = _check_value(kind, key, value)
    if not new.get("name"):
        raise ValueError(f"new {kind} needs a name (fields.name or inventory_id)")
    if kind == "hop":
        if new.get("alpha") is None or not new.get("use"):
            raise ValueError("new hop needs alpha and use (for example Boil, Dry Hop, Aroma)")
    if kind == "fermentable" and new.get("color") is None:
        new["color"] = 0.0
    return new


def _hop_rescale(old: dict, new: dict) -> tuple[float | None, str]:
    old_alpha, new_alpha = old.get("alpha"), new.get("alpha")
    bittering = str(old.get("use") or "").lower() == "boil" and (old.get("time") or 0) >= BITTERING_MIN_TIME
    if not (old_alpha and new_alpha) or not bittering or old.get("amount") is None:
        return None, ""
    return old["amount"] * old_alpha / new_alpha, f"rescaled for alpha {old_alpha:g}->{new_alpha:g}"


def _warn_on_replacement(kind: str, old: dict, new: dict, warnings: list[str]) -> None:
    label = f"{old.get('name')} -> {new.get('name')}"
    if kind == "fermentable":
        old_color, new_color = old.get("color"), new.get("color")
        if new_color is None or (new_color == 0 and old_color):
            warnings.append(f"{label}: colour unknown, set fields.color (SRM)")
        elif old_color is not None and abs(new_color - old_color) > max(1.0, 0.25 * old_color):
            warnings.append(f"{label}: colour {old_color:.1f}->{new_color:.1f} SRM")
        if old.get("grainCategory") and new.get("grainCategory") and old["grainCategory"] != new["grainCategory"]:
            warnings.append(f"{label}: category {old['grainCategory']} -> {new['grainCategory']}")
    elif kind == "hop":
        if new.get("alpha") is None:
            warnings.append(f"{label}: alpha unknown, set fields.alpha")
        elif old.get("alpha") and abs(new["alpha"] - old["alpha"]) > 3:
            warnings.append(f"{label}: alpha {old['alpha']:g}->{new['alpha']:g}")
    elif kind == "yeast":
        for key in ("form", "laboratory"):
            if old.get(key) and new.get(key) and old[key] != new[key]:
                warnings.append(f"{label}: {key} {old[key]} -> {new[key]}")
        if old.get("attenuation") and new.get("attenuation") and abs(old["attenuation"] - new["attenuation"]) > 5:
            warnings.append(f"{label}: attenuation {old['attenuation']:g}->{new['attenuation']:g}%")


def apply_edits(
    base: dict[str, Any],
    edits: list[RecipeEdit],
    *,
    new_name: str,
    notes_append: str | None = None,
    inventory: dict[tuple[str, str], dict] | None = None,
) -> EditOutcome:
    if not edits:
        raise ValueError("Provide at least one edit.")
    if len(edits) > MAX_EDITS:
        raise ValueError(f"At most {MAX_EDITS} edits per call.")
    new_name = " ".join((new_name or "").split())
    if not new_name or len(new_name) > MAX_STRING:
        raise ValueError(f"name must be 1-{MAX_STRING} characters")
    if _norm(new_name) == _norm(base.get("name")):
        raise ValueError("name must differ from the base recipe so the original is never confused with the new one")
    inventory = inventory or {}

    body = copy.deepcopy(base)
    lists: dict[str, list[dict | None]] = {kind: list(body.get(key) or []) for kind, key in LIST_KEY.items()}
    outcome = EditOutcome(body=body, inventory_ids=needed_inventory(edits))

    for edit in edits:
        kind = edit.kind
        items = lists[kind]
        if edit.amount is not None and edit.scale is not None:
            raise ValueError("give amount or scale, not both")
        if edit.scale is not None and (not math.isfinite(edit.scale) or edit.scale <= 0 or edit.scale > 20):
            raise ValueError("scale must be greater than 0 and at most 20")

        if edit.op == "add":
            new = _build_new(kind, edit, inventory)
            if edit.amount is None:
                raise ValueError(f"adding a {kind} needs amount")
            new["amount"] = _check_amount(kind, edit.amount, "amount")
            items.append(new)
            outcome.lines.append(f"+ {kind} {_describe(kind, new)}")
            outcome.changes += 1
            continue

        indexes = _resolve(items, kind, edit.target)
        if edit.amount is not None and len(indexes) > 1:
            raise ValueError(f"{kind} target {edit.target!r} matches {len(indexes)} items; use #n or scale")

        if edit.op == "remove":
            for index in indexes:
                outcome.lines.append(f"- {kind} #{index + 1} {_describe(kind, items[index])}")
                items[index] = None
                outcome.changes += 1
        elif edit.op == "resize":
            if edit.amount is None and edit.scale is None:
                raise ValueError("resize needs amount or scale")
            for index in indexes:
                item = items[index]
                before = _describe(kind, item)
                value = edit.amount if edit.amount is not None else item.get("amount", 0) * edit.scale
                item["amount"] = _check_amount(kind, value, "amount")
                outcome.lines.append(f"~ {kind} #{index + 1} {before} -> {_fmt_amount(kind, item)}")
                outcome.changes += 1
        else:  # replace
            if not edit.inventory_id and not edit.fields:
                raise ValueError("replace needs inventory_id or fields (at least a name)")
            for index in indexes:
                old = items[index]
                new = _build_replacement(kind, old, edit, inventory)
                note = ""
                if edit.amount is not None:
                    new["amount"] = _check_amount(kind, edit.amount, "amount")
                elif edit.scale is not None:
                    new["amount"] = _check_amount(kind, (old.get("amount") or 0) * edit.scale, "amount")
                elif kind == "hop" and edit.keep_ibu:
                    rescaled, note = _hop_rescale(old, new)
                    if rescaled is not None:
                        new["amount"] = _check_amount(kind, rescaled, "amount")
                else:
                    new["amount"] = old.get("amount")
                items[index] = new
                _warn_on_replacement(kind, old, new, outcome.warnings)
                suffix = f" ({note})" if note else ""
                outcome.lines.append(f"> {kind} #{index + 1} {_describe(kind, old)} -> {_describe(kind, new)}{suffix}")
                outcome.changes += 1

    for kind, key in LIST_KEY.items():
        derived = INGREDIENT_DERIVED[kind]
        cleaned = []
        for item in lists[kind]:
            if item is None:
                continue
            cleaned.append({k: v for k, v in item.items() if k not in derived})
        body[key] = cleaned
    if not body["fermentables"] or not body["yeasts"]:
        outcome.warnings.append("result has no fermentables or no yeast")

    for key in [k for k in body if k.startswith("_") or k in ROOT_DERIVED or k in ROOT_INSTANCE_BOUND]:
        del body[key]
    body["name"] = new_name
    body["public"] = False
    if notes_append:
        extra = "".join(ch for ch in notes_append if ch == "\n" or ch >= " ")[:MAX_NOTES_APPEND].strip()
        if extra:
            existing = str(body.get("notes") or "").rstrip()
            body["notes"] = f"{existing}\n\n{extra}" if existing else extra
    return outcome


METRICS = (("og", "OG", "{:.3f}"), ("fg", "FG", "{:.3f}"), ("abv", "ABV", "{:.2f}"), ("ibu", "IBU", "{:.1f}"), ("color", "SRM", "{:.1f}"))


def compare_metrics(base: dict[str, Any], new: dict[str, Any]) -> tuple[str, bool]:
    """One-line before/after for the main numbers, and whether the new recipe was calculated."""
    parts: list[str] = []
    calculated = False
    for key, label, pattern in METRICS:
        before, after = base.get(key), new.get(key)
        if after is not None:
            calculated = True
        left = pattern.format(before) if isinstance(before, (int, float)) else "?"
        right = pattern.format(after) if isinstance(after, (int, float)) else "?"
        parts.append(f"{label} {left}->{right}")
    return " | ".join(parts), calculated


def metrics_line(raw: dict[str, Any]) -> str:
    parts = [
        f"{label} {pattern.format(raw[key])}"
        for key, label, pattern in METRICS
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool)
    ]
    return " ".join(parts) or "not calculated"


def _g(value: Any) -> str:
    return "?" if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) else f"{value:g}"


def _steps(profile: Any, unit: str) -> str:
    steps = (profile or {}).get("steps") if isinstance(profile, dict) else None
    return ", ".join(f"{_g(s.get('stepTemp'))}C/{_g(s.get('stepTime'))}{unit}" for s in steps or [] if isinstance(s, dict))


def ingredient_table(raw: dict[str, Any], *, notes_limit: int = 400) -> str:
    """Compact numbered working table of a recipe. Row numbers are the #n used by RecipeEdit targets."""
    from brewfather_mcp.formatter import untrusted

    head = (
        f"{raw.get('name')} | {raw.get('type')} | {_g(raw.get('batchSize'))}L batch, boil {_g(raw.get('boilTime'))}min, "
        f"eff {_g(raw.get('efficiency'))}% | {metrics_line(raw)} | id {raw.get('_id')}"
    )
    lines = [head, "(# = position; kg/g/pkg amounts; SRM colour; AA alpha %)"]

    lines.append("fermentables: #|name|supplier|kg|SRM|category|type")
    for i, f in enumerate(raw.get("fermentables") or [], 1):
        lines.append("|".join([f"#{i}", str(f.get("name")), str(f.get("supplier") or ""), _g(f.get("amount")), _g(round(f["color"], 1) if isinstance(f.get("color"), (int, float)) else None), str(f.get("grainCategory") or ""), str(f.get("type") or "")]))

    lines.append("hops: #|name|origin|g|AA|use|time|temp|form|year")
    for i, h in enumerate(raw.get("hops") or [], 1):
        unit = "d" if h.get("timeUnit") in ("day", "days") else "m"
        time = f"{_g(h.get('time'))}{unit}" if h.get("time") is not None else ""
        lines.append("|".join([f"#{i}", str(h.get("name")), str(h.get("origin") or ""), _g(h.get("amount")), _g(h.get("alpha")), str(h.get("use") or ""), time, _g(h.get("temp")) if h.get("temp") is not None else "", str(h.get("type") or ""), _g(h.get("year")) if h.get("year") is not None else ""]))

    lines.append("yeasts: #|name|lab|productId|amount|form|att%|type")
    for i, y in enumerate(raw.get("yeasts") or [], 1):
        lines.append("|".join([f"#{i}", str(y.get("name")), str(y.get("laboratory") or ""), str(y.get("productId") or ""), f"{_g(y.get('amount'))}{y.get('unit') or ''}", str(y.get("form") or ""), _g(y.get("attenuation")), str(y.get("type") or "")]))

    if raw.get("miscs"):
        lines.append("miscs: #|name|type|amount|use|time")
        for i, m in enumerate(raw.get("miscs") or [], 1):
            unit = "d" if m.get("timeIsDays") else "m"
            time = f"{_g(m.get('time'))}{unit}" if m.get("time") is not None else ""
            lines.append("|".join([f"#{i}", str(m.get("name")), str(m.get("type") or ""), f"{_g(m.get('amount'))}{m.get('unit') or ''}", str(m.get("use") or ""), time]))

    mash = _steps(raw.get("mash"), "m")
    ferment = _steps(raw.get("fermentation"), "d")
    if mash:
        lines.append(f"mash: {mash}")
    if ferment:
        lines.append(f"fermentation: {ferment}")
    notes = " ".join(str(raw.get("notes") or "").split())
    if notes:
        lines.append("notes: " + untrusted(notes[:notes_limit] + ("…" if len(notes) > notes_limit else "")))
    return "\n".join(lines)
