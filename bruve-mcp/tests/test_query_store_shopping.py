import re

import pytest

from bruve_mcp.query import build_match
from bruve_mcp.shopping import cover, plan_line
from bruve_mcp.links import cart_link, product_link, variation_params
from bruve_mcp.store import Store


class TestQuery:
    def test_words_are_anded_and_prefixed(self):
        assert build_match("Centennial") == '"centennial"*'
        assert build_match("Pale Ale") == '"pale"* AND "ale"*'

    def test_diacritics_and_german_variants_fold(self):
        assert build_match("Hallertauer Mittelfrueh") == build_match("Hallertauer Mittelfrüh")

    def test_hyphenated_codes_become_phrases(self):
        assert build_match("US-05") == '"us 05"'
        assert build_match("W-34/70") == '"w 34 70"'

    def test_synonyms_expand_latvian_and_english(self):
        match = build_match("hops")
        assert '"apini"*' in match and '"hops"*' in match and " OR " in match
        assert '"kviesu"*' in build_match("wheat malt")

    def test_loose_uses_or(self):
        assert build_match("Cara Pils", loose=True) == '("cara"* OR ' + build_match("Cara Pils", loose=True).split("OR ", 1)[1]

    def test_stop_words_and_empty(self):
        assert build_match("the of and") is None
        assert build_match("Centennial pellet") == '"centennial"*'
        assert build_match("   ") is None

    def test_no_fts_syntax_injection(self):
        match = build_match('foo" OR "bar* NEAR(x) -y ^z col:val')
        assert match is not None
        # Only quoted/prefixed words, parentheses and the AND/OR operators we generate may appear.
        remaining = re.sub(r'"[a-z0-9 ]+"\*?', "", match)
        assert re.fullmatch(r"[\s()]*((AND|OR)[\s()]*)*", remaining), remaining


class TestStoreSearch:
    @pytest.fixture
    async def store(self, runtime):
        return runtime.store

    async def test_text_search_ignores_diacritics(self, store):
        rows, total, _ = store.search(match=build_match("avenu skabais"))
        assert total == 0
        rows, total, _ = store.search(match=build_match("kviesu"))
        assert any("Kviešu" in r["name"] for r in rows)

    async def test_kind_and_ebc_overlap_filters(self, store):
        rows, total, unknown = store.search(kind="malt", ebc=(2, 6), sort="ebc", limit=25)
        assert total == len(rows) > 0
        assert all(r["ebc_max"] >= 2 and r["ebc_min"] <= 6 for r in rows)
        assert [r["ebc_min"] for r in rows] == sorted(r["ebc_min"] for r in rows)
        assert "ebc" in unknown

    async def test_alpha_filter_excludes_and_counts_unknown(self, store):
        rows, total, unknown = store.search(kind="hop", alpha=(10, 20), sort="alpha")
        assert all(r["alpha_max"] >= 10 for r in rows)
        assert unknown["alpha"] >= 1

    async def test_unknown_counts_only_include_relevant_kinds(self, store):
        _, _, unknown = store.search(alpha=(5, 10))
        everything_else = store._db.execute("SELECT COUNT(*) FROM products WHERE kind != 'hop' AND alpha_min IS NULL").fetchone()[0]
        assert everything_else > 0 and unknown["alpha"] < everything_else

    async def test_role_filter_and_brand_filter(self, store):
        rows, _, _ = store.search(kind="malt", role="caramel", limit=25)
        assert rows and all("caramel" in r["role"] for r in rows)
        rows, _, _ = store.search(kind="yeast", brand="fermentis", limit=25)
        assert rows and all((r["lab"] or "") == "Fermentis" for r in rows)
        rows, _, _ = store.search(brand="Swaen", limit=25)
        assert rows

    async def test_pagination_offset(self, store):
        first, total, _ = store.search(kind="yeast", sort="name", limit=3, offset=0)
        second, _, _ = store.search(kind="yeast", sort="name", limit=3, offset=3)
        assert total > 6 and not {r["id"] for r in first} & {r["id"] for r in second}

    async def test_search_is_parameterized(self, store):
        rows, total, _ = store.search(kind="malt'; DROP TABLE products;--")
        assert total == 0 and store.product_count() > 0

    async def test_overview_stats(self, store):
        stats = store.overview_stats()
        assert stats["kinds"]["malt"] > 0 and stats["ebc"][0] is not None and stats["alpha"][3] > 0

    async def test_exact_code_match_ranks_first(self, store):
        rows, _, _ = store.search(match=build_match("US-05"), limit=3)
        assert rows and rows[0]["code"] == "US-05"


class TestCover:
    PACKS = [
        {"size": 100, "price": 695, "limit": None},
        {"size": 500, "price": 2928, "limit": None},
        {"size": 5000, "price": 20873, "limit": 1},
    ]

    def test_prefers_cheapest_combination(self):
        chosen, cost, total = cover(350, self.PACKS)
        assert [(p["size"], c) for p, c in chosen] == [(100, 4)] and cost == 2780 and total == 400

    def test_larger_pack_wins_when_cheaper(self):
        chosen, cost, total = cover(450, self.PACKS)
        assert [(p["size"], c) for p, c in chosen] == [(500, 1)] and cost == 2928

    def test_mixed_packs(self):
        chosen, cost, total = cover(1100, self.PACKS)
        assert sorted((p["size"], c) for p, c in chosen) == [(100, 1), (500, 2)] and total == 1100

    def test_prefers_less_overshoot_on_price_ties(self):
        packs = [{"size": 100, "price": 100, "limit": None}, {"size": 200, "price": 200, "limit": None}]
        chosen, cost, total = cover(150, packs)
        assert total == 200 and cost == 200

    def test_stock_limits_are_respected(self):
        packs = [{"size": 100, "price": 500, "limit": 2}]
        assert cover(200, packs) is not None
        assert cover(250, packs) is None

    def test_invalid_inputs(self):
        assert cover(0, self.PACKS) is None
        assert cover(10, []) is None


class TestPlanLine:
    async def _row(self, runtime, product_id):
        return runtime.store.get_products([product_id])[0], runtime.store.get_packs([product_id]).get(product_id, [])

    async def test_malt_rounds_up_to_tenth_of_kg_and_reports_shortfall(self, runtime):
        row, packs = await self._row(runtime, 1008088)
        result = plan_line(row, packs, 1.67, "kg", None)
        assert result.buy == "1.7kg" and result.cost_cents == round(1.7 * row["price_cents"])
        assert plan_line(row, packs, 500, "kg", None).note.startswith("short: only")
        assert plan_line(row, packs, 250, "g", None).buy == "0.3kg"
        assert plan_line(row, packs, 2, "pk", None).note.startswith("sold by weight")

    async def test_hop_pack_combination(self, runtime):
        row, packs = await self._row(runtime, 1002534)
        result = plan_line(row, packs, 350, "g", None)
        assert result.buy == "4x100g y2025" and result.cost_cents == 4 * 695
        assert "over need" in result.note

    async def test_explicit_pack_and_not_found(self, runtime):
        row, packs = await self._row(runtime, 1002534)
        assert plan_line(row, packs, 2, "pk", "500g").buy == "2x500g y2025"
        assert "not found" in plan_line(row, packs, 2, "pk", "250g").note
        assert "count" in plan_line(row, packs, 200, "g", "500g").note

    async def test_single_pack_variable_product_accepts_pk(self, runtime):
        row, packs = await self._row(runtime, 1000697)
        assert len(packs) == 1
        result = plan_line(row, packs, 1, "pk", None)
        assert result.buy.startswith("1x11g") and result.cost_cents == packs[0]["price_cents"] > 0

    async def test_yeast_sachets(self, runtime):
        row, packs = await self._row(runtime, 1007741)
        assert not packs
        assert plan_line(row, packs, 2, "pk", None).buy == "2x15g"
        assert plan_line(row, packs, 20, "g", None).buy == "2x15g"

    async def test_invalid_units_and_needs(self, runtime):
        row, packs = await self._row(runtime, 1008088)
        assert "unit must be" in plan_line(row, packs, 1, "lbs", None).note
        assert "greater than zero" in plan_line(row, packs, 0, "kg", None).note
        assert "greater than zero" in plan_line(row, packs, float("nan"), "kg", None).note


class TestLinks:
    PACK = {"label": "Iepakojums: 100g, Gads: 2025", "variation_id": 1005115}

    def test_variation_params_known_attributes(self):
        assert variation_params(self.PACK) == {"attribute_pa_iepakojums": "100g", "attribute_gads": "2025"}

    def test_unknown_attribute_falls_back_to_product_page(self):
        pack = {"label": "Krāsa: Zils", "variation_id": 1}
        assert variation_params(pack) is None
        assert cart_link(5, 1, pack) is None
        assert product_link("https://bruve.lv/veikals/x/", pack) == "https://bruve.lv/veikals/x/"

    def test_cart_link_for_variation_and_simple_product(self):
        link = cart_link(1002534, 4, self.PACK)
        assert link.startswith("https://bruve.lv/?add-to-cart=1002534&quantity=4&variation_id=1005115")
        assert "attribute_pa_iepakojums=100g" in link and "attribute_gads=2025" in link
        assert cart_link(1008088, 1.7) == "https://bruve.lv/?add-to-cart=1008088&quantity=1.7"
