"""Tests for the substitution knowledge validator and the knowledge files themselves.

The knowledge lives in the workspace-level skill folder next to this project, so these tests are skipped
when that folder is not present (for example when bruve-mcp is checked out on its own).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[2] / ".github" / "skills" / "ingredient-substitution"
SCRIPT = SKILL_DIR / "validate_knowledge.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="ingredient-substitution skill folder not found")


@pytest.fixture(scope="module")
def vk():
    spec = importlib.util.spec_from_file_location("validate_knowledge", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves string annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def write_files(directory: Path, **overrides: str) -> None:
    valid = {
        "malt.md": "M-PILS | Pilsner; Pilsen | close | same role and colour, mild change | draft\n",
        "hop.md": "H-NOBLE | Saaz; Tettnang | fair | spicy and herbal noble hops | draft\n",
        "yeast.md": "Y-US | US-05; WLP001 | close | clean American ale strain family | draft\n",
        "misc.md": "X-FINING | Irish moss; Whirlfloc | close | boil clarifiers, dose by product | draft\n",
    }
    valid.update(overrides)
    for name, text in valid.items():
        (directory / name).write_text(text, "utf-8")


class TestRealKnowledgeFiles:
    def test_files_pass_format_validation(self, vk):
        groups, errors = vk.load_groups()
        errors += vk.validate(groups)
        assert errors == []
        assert len(groups) >= 90

    def test_every_file_has_all_tiers_of_guidance(self, vk):
        groups, _ = vk.load_groups()
        for name in vk.PREFIX_BY_FILE:
            tiers = {g.tier for g in groups if g.file == name}
            assert {"close", "fair"} <= tiers and "never" in tiers, name

    def test_nothing_claims_to_be_reviewed_without_a_human(self, vk):
        groups, _ = vk.load_groups()
        assert {g.review for g in groups} == {"draft"}

    def test_acceptance_ingredients_are_known(self, vk):
        groups, _ = vk.load_groups()
        ingredients = {
            "Pilsner": "malt.md", "Pilsen": "malt.md", "Wheat Malt": "malt.md", "Acidulated": "malt.md",
            "Carapils": "malt.md", "Oats, Flaked": "malt.md", "Centennial": "hop.md", "Saaz": "hop.md",
            "Philly Sour": "yeast.md", "US-05": "yeast.md", "Irish Moss": "misc.md", "Yeast Nutrients": "misc.md",
        }
        for name, file in ingredients.items():
            assert vk.covering_groups(groups, name, (file,)), name

    def test_pilsner_options_include_the_two_shop_malts_from_the_brief(self, vk):
        groups, _ = vk.load_groups()
        assert vk.covering_groups(groups, "Latmalt Pilsner Miežu Iesals (4-6 EBC)", ("malt.md",))
        assert vk.covering_groups(groups, "BestMalz Pilsen 3-4.9 EBC", ("malt.md",))


class TestNormalisation:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("Hallertauer Mittelfrüh", "hallertauer mittelfrueh"),
            ("Idaho-7", "Idaho 7"),
            ("Aveņu Skābais", "avenu skabais"),
            ("WildBrew™ Philly Sour", "wildbrew philly sour"),
            ("Gold Swaen© Light", "gold swaen light"),
        ],
    )
    def test_equivalent_spellings(self, vk, a, b):
        assert vk.norm(a) == vk.norm(b)

    def test_whole_words_only(self, vk):
        groups = [vk.Group("hop.md", 1, "H-X", ["Cascade", "Centennial"], "fair", "same family of hops", "draft")]
        assert vk.covering_groups(groups, "Cascade Apiņi T90 USA", ("hop.md",))
        assert not vk.covering_groups(groups, "Cascadello Apiņi", ("hop.md",))
        assert not vk.covering_groups(groups, "Cascade Apiņi", ("malt.md",))

    def test_never_groups_count_as_coverage(self, vk):
        groups = [vk.Group("malt.md", 1, "M-X", ["Lactose", "Milk sugar"], "never", "not fermentable at all", "draft")]
        assert vk.covering_groups(groups, "Laktoze Lactose 500g", ("malt.md",))


class TestValidation:
    def test_valid_set_passes(self, vk, tmp_path):
        write_files(tmp_path)
        groups, errors = vk.load_groups(tmp_path)
        assert errors == [] and vk.validate(groups) == []

    @pytest.mark.parametrize(
        "line,message",
        [
            ("M-PILS | Pilsner; Pilsen | sorta | same role and colour, mild change | draft", "tier"),
            ("M-PILS | Pilsner; Pilsen | close | same role and colour, mild change | maybe", "review"),
            ("M-PILS | Pilsner | close | same role and colour, mild change | draft", "at least 2 members"),
            ("M-PILS | Pilsner; pilsner | close | same role and colour, mild change | draft", "repeats a member"),
            ("M-PILS | Idaho-7; Idaho 7 | close | same role and colour, mild change | draft", "repeats a member"),
            ("X-PILS | Pilsner; Pilsen | close | same role and colour, mild change | draft", "id must look like"),
            ("m-pils | Pilsner; Pilsen | close | same role and colour, mild change | draft", "id must look like"),
            ("M-PILS | Pilsner; Pilsen | close | short | draft", "too short"),
        ],
    )
    def test_invalid_lines_are_reported(self, vk, tmp_path, line, message):
        write_files(tmp_path, **{"malt.md": line + "\n"})
        groups, errors = vk.load_groups(tmp_path)
        assert any(message in e for e in errors + vk.validate(groups))

    def test_wrong_field_count_and_missing_file(self, vk, tmp_path):
        write_files(tmp_path, **{"malt.md": "M-PILS | Pilsner; Pilsen | close | only four fields\n"})
        (tmp_path / "misc.md").unlink()
        _, errors = vk.load_groups(tmp_path)
        assert any("expected 5 fields" in e for e in errors) and any("misc.md: file is missing" in e for e in errors)

    def test_duplicate_ids_are_caught(self, vk, tmp_path):
        line = "M-PILS | Pilsner; Pilsen | close | same role and colour, mild change | draft\n"
        write_files(tmp_path, **{"malt.md": line + line})
        groups, _ = vk.load_groups(tmp_path)
        assert any("duplicate id" in e for e in vk.validate(groups))

    def test_comments_and_blank_lines_are_ignored(self, vk, tmp_path):
        write_files(tmp_path, **{"malt.md": "# a comment\n\nM-PILS | Pilsner; Pilsen | close | same role and colour, mild change | draft\n"})
        groups, errors = vk.load_groups(tmp_path)
        assert errors == [] and len(groups) == 4


class TestCoverage:
    def test_reports_uncovered_items(self, vk):
        groups = [vk.Group("hop.md", 1, "H-X", ["Cascade", "Centennial"], "fair", "same family of hops", "draft")]
        products = [("hop", "Cascade Apiņi T90 USA"), ("hop", "Mystery Hop T90"), ("malt", "Pilsner")]
        result = vk.coverage(groups, products)
        assert result["hop"] == (1, ["Mystery Hop T90"])
        assert result["malt"] == (0, ["Pilsner"])

    def test_reads_the_cache_read_only(self, vk, tmp_path):
        import sqlite3

        path = tmp_path / "catalogue.sqlite3"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE products (kind TEXT, name TEXT, in_stock INTEGER)")
        db.executemany("INSERT INTO products VALUES (?,?,?)", [("hop", "Saaz", 1), ("hop", "Gone", 0)])
        db.commit()
        db.close()
        assert vk.read_products(path) == [("hop", "Saaz")]
