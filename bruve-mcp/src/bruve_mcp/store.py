"""Local SQLite + FTS5 cache of the shop's ingredient catalogue."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .parse.common import fold

PRODUCT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("id", "INTEGER PRIMARY KEY"),
    ("name", "TEXT NOT NULL"),
    ("url", "TEXT"),
    ("kind", "TEXT NOT NULL"),
    ("brand", "TEXT"),
    ("type", "TEXT"),
    ("in_stock", "INTEGER"),
    ("price_cents", "INTEGER"),
    ("price_max_cents", "INTEGER"),
    ("sold_by", "TEXT"),
    ("stock_qty", "REAL"),
    ("cats", "TEXT"),
    ("desc", "TEXT"),
    ("pack_size", "REAL"),
    ("pack_unit", "TEXT"),
    ("pack_label", "TEXT"),
    ("role", "TEXT"),
    ("ebc_min", "REAL"),
    ("ebc_max", "REAL"),
    ("srm_min", "REAL"),
    ("srm_max", "REAL"),
    ("colour_src", "TEXT"),
    ("alpha_min", "REAL"),
    ("alpha_max", "REAL"),
    ("alpha", "REAL"),
    ("alpha_src", "TEXT"),
    ("attr_alpha", "TEXT"),
    ("hop_form", "TEXT"),
    ("origin", "TEXT"),
    ("title_year", "INTEGER"),
    ("years", "TEXT"),
    ("lab", "TEXT"),
    ("code", "TEXT"),
    ("yeast_form", "TEXT"),
    ("form_src", "TEXT"),
    ("att_min", "REAL"),
    ("att_max", "REAL"),
    ("floc", "TEXT"),
    ("temp_min", "REAL"),
    ("temp_max", "REAL"),
    ("abv_tol", "REAL"),
    ("tags", "TEXT"),
)
COLUMN_NAMES = tuple(name for name, _ in PRODUCT_COLUMNS)

PACK_COLUMNS = ("variation_id", "product_id", "label", "year", "size", "unit", "price_cents", "in_stock", "stock_qty")

SORTS_SQL = {
    "price": "p.price_cents ASC",
    "name": "p.name COLLATE NOCASE ASC",
    "ebc": "COALESCE(p.ebc_min, 99999) ASC",
    "alpha": "COALESCE(p.alpha, -1) DESC",
}
CHANGE_LOG_LIMIT = 500


def default_cache_dir() -> Path:
    override = os.getenv("BRUVE_MCP_CACHE_DIR")
    if override:
        return Path(override)
    base = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "bruve-mcp"


def _schema() -> list[str]:
    columns = ", ".join(f'"{name}" {decl}' for name, decl in PRODUCT_COLUMNS)
    return [
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
        f"CREATE TABLE IF NOT EXISTS products ({columns})",
        "CREATE INDEX IF NOT EXISTS ix_products_kind ON products(kind)",
        "CREATE TABLE IF NOT EXISTS packs (variation_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, "
        "label TEXT, year INTEGER, size REAL, unit TEXT, price_cents INTEGER, in_stock INTEGER, stock_qty REAL)",
        "CREATE INDEX IF NOT EXISTS ix_packs_product ON packs(product_id)",
        "CREATE TABLE IF NOT EXISTS changes (ts REAL, product_id INTEGER, name TEXT, field TEXT, old TEXT, new TEXT)",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(name, brand, tags, tokenize='unicode61 remove_diacritics 2')",
    ]


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            for statement in _schema():
                self._db.execute(statement)
            self._db.commit()

    # -- meta ---------------------------------------------------------------------------------
    def _meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def synced_at(self) -> float | None:
        with self._lock:
            value = self._meta("synced_at")
            return float(value) if value else None

    def product_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # -- writing ------------------------------------------------------------------------------
    def replace_catalogue(self, products: list[dict[str, Any]], packs: list[dict[str, Any]]) -> int:
        """Replace the cache atomically and return how many price/stock/availability changes were logged."""
        now = time.time()
        years_by_product: dict[int, set[int]] = {}
        for pack in packs:
            if pack.get("year"):
                years_by_product.setdefault(pack["product_id"], set()).add(pack["year"])
        for product in products:
            years = set(years_by_product.get(product["id"], set()))
            if product.get("title_year"):
                years.add(product["title_year"])
            product["years"] = ",".join(str(y) for y in sorted(years)) or None

        with self._lock:
            old = {row["id"]: row for row in self._db.execute(
                "SELECT id, name, price_cents, in_stock, stock_qty FROM products")}
            changes: list[tuple] = []
            new_ids = set()
            for product in products:
                new_ids.add(product["id"])
                prior = old.get(product["id"])
                if prior is None:
                    if old:
                        changes.append((now, product["id"], product["name"], "added", None, None))
                    continue
                for field in ("price_cents", "in_stock", "stock_qty"):
                    if prior[field] != product.get(field) and not (
                        field == "in_stock" and bool(prior[field]) == bool(product.get(field))
                    ):
                        changes.append((now, product["id"], product["name"], field, prior[field], product.get(field)))
            for product_id, prior in old.items():
                if product_id not in new_ids:
                    changes.append((now, product_id, prior["name"], "removed", None, None))

            with self._db:
                self._db.execute("DELETE FROM products")
                self._db.execute("DELETE FROM packs")
                self._db.execute("DELETE FROM fts")
                placeholders = ",".join("?" for _ in COLUMN_NAMES)
                quoted = ",".join(f'"{name}"' for name in COLUMN_NAMES)
                for product in products:
                    values = [
                        int(product.get(name)) if name == "in_stock" and product.get(name) is not None else product.get(name)
                        for name in COLUMN_NAMES
                    ]
                    self._db.execute(f"INSERT INTO products ({quoted}) VALUES ({placeholders})", values)
                    self._db.execute(
                        "INSERT INTO fts(rowid, name, brand, tags) VALUES (?, ?, ?, ?)",
                        (product["id"], fold(product["name"]), fold(product.get("brand") or ""), fold(_tag_text(product))),
                    )
                for pack in packs:
                    self._db.execute(
                        f"INSERT OR REPLACE INTO packs ({','.join(PACK_COLUMNS)}) VALUES ({','.join('?' for _ in PACK_COLUMNS)})",
                        [int(pack[c]) if c == "in_stock" else pack.get(c) for c in PACK_COLUMNS],
                    )
                if changes:
                    self._db.executemany("INSERT INTO changes VALUES (?,?,?,?,?,?)", [
                        (ts, pid, name, field, None if o is None else str(o), None if n is None else str(n))
                        for ts, pid, name, field, o, n in changes
                    ])
                    self._db.execute(
                        "DELETE FROM changes WHERE rowid NOT IN (SELECT rowid FROM changes ORDER BY ts DESC, rowid DESC LIMIT ?)",
                        (CHANGE_LOG_LIMIT,),
                    )
                self._db.execute("INSERT OR REPLACE INTO meta VALUES ('synced_at', ?)", (str(now),))
            return len(changes)

    def apply_live_product(self, product_id: int, *, price_cents: int | None, in_stock: bool, stock_qty: float | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE products SET price_cents = COALESCE(?, price_cents), in_stock = ?, stock_qty = ? WHERE id = ?",
                (price_cents, int(in_stock), stock_qty, product_id),
            )

    def apply_live_pack(self, variation_id: int, *, price_cents: int | None, in_stock: bool, stock_qty: float | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE packs SET price_cents = COALESCE(?, price_cents), in_stock = ?, stock_qty = ? WHERE variation_id = ?",
                (price_cents, int(in_stock), stock_qty, variation_id),
            )

    # -- reading ------------------------------------------------------------------------------
    def get_products(self, ids: list[int]) -> list[sqlite3.Row]:
        if not ids:
            return []
        with self._lock:
            marks = ",".join("?" for _ in ids)
            rows = self._db.execute(f"SELECT * FROM products WHERE id IN ({marks})", ids).fetchall()
        order = {pid: i for i, pid in enumerate(ids)}
        return sorted(rows, key=lambda r: order[r["id"]])

    def get_packs(self, product_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
        out: dict[int, list[sqlite3.Row]] = {}
        if not product_ids:
            return out
        with self._lock:
            marks = ",".join("?" for _ in product_ids)
            rows = self._db.execute(
                f"SELECT * FROM packs WHERE product_id IN ({marks}) ORDER BY product_id, unit, size, year", product_ids
            ).fetchall()
        for row in rows:
            out.setdefault(row["product_id"], []).append(row)
        return out

    def search(
        self,
        *,
        match: str | None = None,
        kind: str | None = None,
        brand: str | None = None,
        role: str | None = None,
        in_stock: bool | None = True,
        ebc: tuple[float | None, float | None] = (None, None),
        alpha: tuple[float | None, float | None] = (None, None),
        sort: str = "relevance",
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int, dict[str, int]]:
        """Return (rows, total_matches, unknown_counts) where unknown_counts lists rows excluded by missing data."""
        where: list[str] = []
        params: list[Any] = []
        join = ""
        if match:
            join = "JOIN fts ON fts.rowid = p.id"
            where.append("fts MATCH ?")
            params.append(match)
        if kind:
            where.append("p.kind = ?")
            params.append(kind)
        if brand:
            where.append("(p.brand LIKE ? OR p.lab LIKE ? OR p.name LIKE ?)")
            params.extend([f"%{brand}%", f"%{brand}%", f"%{brand}%"])
        if role:
            where.append("(',' || COALESCE(p.role,'') || ',') LIKE ?")
            params.append(f"%,{role},%")
        if in_stock is True:
            where.append("p.in_stock = 1")
        elif in_stock is False:
            where.append("p.in_stock = 0")

        base_where, base_params = list(where), list(params)
        range_where: list[str] = []
        range_params: list[Any] = []
        unknown_checks: list[tuple[str, str, str]] = []
        for label, (low, high), col_min, col_max, kinds_sql in (
            ("ebc", ebc, "ebc_min", "ebc_max", "('malt','extract','adjunct_grain')"),
            ("alpha", alpha, "alpha_min", "alpha_max", "('hop')"),
        ):
            if low is None and high is None:
                continue
            clause = [f"p.{col_min} IS NOT NULL"]
            if low is not None:
                clause.append(f"p.{col_max} >= ?")
                range_params.append(low)
            if high is not None:
                clause.append(f"p.{col_min} <= ?")
                range_params.append(high)
            range_where.append(" AND ".join(clause))
            unknown_checks.append((label, col_min, kinds_sql))
        where += range_where
        params += range_params

        unknown: dict[str, int] = {}
        with self._lock:
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            total = self._db.execute(f"SELECT COUNT(*) FROM products p {join} {where_sql}", params).fetchone()[0]
            for label, col_min, kinds_sql in unknown_checks:
                unknown_sql = "WHERE " + " AND ".join(base_where + [f"p.{col_min} IS NULL", f"p.kind IN {kinds_sql}"])
                unknown[label] = self._db.execute(
                    f"SELECT COUNT(*) FROM products p {join} {unknown_sql}", base_params
                ).fetchone()[0]

            if match and sort == "relevance":
                order = "p.in_stock DESC, bm25(fts, 6.0, 2.0, 1.0) ASC, p.id ASC"
            else:
                order = f"{SORTS_SQL.get(sort, SORTS_SQL['name'])}, p.id ASC"
            rows = self._db.execute(
                f"SELECT p.* FROM products p {join} {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return rows, total, unknown

    def overview_stats(self) -> dict[str, Any]:
        with self._lock:
            kinds = {
                r["kind"]: r["n"]
                for r in self._db.execute("SELECT kind, COUNT(*) AS n FROM products WHERE in_stock = 1 GROUP BY kind ORDER BY n DESC")
            }
            brands: dict[str, list[str]] = {}
            for r in self._db.execute(
                "SELECT kind, COALESCE(lab, brand) AS b, COUNT(*) AS n FROM products WHERE in_stock = 1 AND COALESCE(lab, brand) IS NOT NULL "
                "GROUP BY kind, b ORDER BY kind, n DESC"
            ):
                brands.setdefault(r["kind"], []).append(f'{r["b"]}({r["n"]})')
            ebc = self._db.execute("SELECT MIN(ebc_min), MAX(ebc_max) FROM products WHERE kind = 'malt'").fetchone()
            alpha = self._db.execute(
                "SELECT MIN(alpha_min), MAX(alpha_max), SUM(alpha IS NOT NULL), COUNT(*) FROM products WHERE kind = 'hop'"
            ).fetchone()
            roles = {
                r["role"]: r["n"]
                for r in self._db.execute(
                    "SELECT role, COUNT(*) AS n FROM products WHERE role IS NOT NULL AND in_stock = 1 GROUP BY role ORDER BY n DESC"
                )
            }
            return {
                "synced_at": self.synced_at(),
                "total": self.product_count(),
                "kinds": kinds,
                "brands": brands,
                "ebc": (ebc[0], ebc[1]),
                "alpha": (alpha[0], alpha[1], alpha[2], alpha[3]),
                "roles": roles,
            }

    def recent_changes(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute("SELECT * FROM changes ORDER BY ts DESC, rowid DESC LIMIT ?", (limit,)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _tag_text(product: dict[str, Any]) -> str:
    parts = [
        product.get("tags"),
        product.get("role"),
        product.get("lab"),
        product.get("code"),
        product.get("origin"),
        product.get("hop_form"),
        product.get("years"),
        product.get("pack_label"),
    ]
    return " ".join(str(p) for p in parts if p)
