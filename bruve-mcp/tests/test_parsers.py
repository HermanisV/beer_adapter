import pytest

from bruve_mcp.parse import normalize_product
from bruve_mcp.parse.common import (
    clean_text,
    fold,
    kind_for,
    pack_label,
    parse_pack,
    parse_variation_label,
    stock_quantity,
)
from bruve_mcp.parse.hop import parse_alpha, parse_hop_title
from bruve_mcp.parse.malt import ebc_to_srm, parse_colour
from bruve_mcp.parse.yeast import detect_code, detect_form, detect_lab, parse_performance


class TestCommon:
    def test_clean_text_decodes_entities_and_tags(self):
        assert clean_text("Mangrove Jack&#8217;s <b>Sidra</b>&nbsp;Raugs &#8211; 9 g") == "Mangrove Jack’s Sidra Raugs – 9 g"

    def test_fold_removes_diacritics_and_german_variants(self):
        assert fold("Aveņu Skābais") == "avenu skabais"
        assert fold("Hallertauer Mittelfrüh") == fold("Hallertauer Mittelfrueh") == fold("Hallertauer Mittelfruh")
        assert fold("Hüll Melon") == fold("Huell Melon")

    def test_fold_drops_trademark_signs_instead_of_spelling_them(self):
        assert fold("Lallemand WildBrew™ Philly Sour") == "lallemand wildbrew philly sour"
        assert fold("Fermentis SafCider™ AS-2") == "fermentis safcider as-2"
        assert fold("BestMalz® Pale© Ale™") == "bestmalz pale ale"

    @pytest.mark.parametrize(
        "text,expected",
        [("15 g", (15, "g")), ("1,5 kg", (1500, "g")), ("23L", (23000, "ml")), ("Rīsu Sēnalas – 1KG", (1000, "g")), ("100 gab.", (100, "pcs"))],
    )
    def test_parse_pack(self, text, expected):
        assert parse_pack(text) == expected

    def test_parse_pack_none(self):
        assert parse_pack("Fermentis SafAle US-05") is None

    def test_pack_label(self):
        assert pack_label(1500, "g") == "1.5kg"
        assert pack_label(11.5, "g") == "11.5g"
        assert pack_label(23000, "ml") == "23L"

    def test_stock_quantity_treats_9999_as_unmanaged(self):
        assert stock_quantity({"maximum": 61.2}) == 61.2
        assert stock_quantity({"maximum": 9999}) is None
        assert stock_quantity(None) is None
        assert stock_quantity({"maximum": "x"}) is None

    def test_variation_label(self):
        assert parse_variation_label("Iepakojums: 5kg, Gads: 2026") == {"Iepakojums": "5kg", "Gads": "2026"}
        assert parse_variation_label(None) == {}

    @pytest.mark.parametrize(
        "slugs,title,kind",
        [
            ({"apini"}, "x", "hop"),
            ({"iesali", "bazes-iesals"}, "x", "malt"),
            ({"iesali", "cits"}, "Pārsloti Rīsi (Rīsu pārslas) 1kg", "adjunct_grain"),
            ({"alus-raugi", "enzimi-un-bakterijas"}, "x", "enzyme"),
            ({"alus-raugi", "vina-raugi"}, "x", "yeast"),
            ({"citi", "parslas-un-citi-graudi", "piedevas"}, "x", "adjunct_grain"),
            ({"iesala-ekstrakts-iesals", "skidrie-iesala-ekstrakti"}, "x", "extract"),
            ({"unknown"}, "x", "additive"),
        ],
    )
    def test_kind_for(self, slugs, title, kind):
        assert kind_for(slugs, title) == kind


class TestMaltColour:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("BestMalz Caramel Aromatic (41-60 EBC)", (41, 60)),
            ("BestMalz Pilsen 3-4.9 EBC", (3, 4.9)),
            ("BestMalz Graudzēts Kviešu iesals (2.8 – 5 EBC)", (2.8, 5)),
            ("Platinum Swaen© Stroopwafel (EBC 60-80)", (60, 80)),
            ("Platinum Swaen© Sauer-skābais (14 EBC)", (14, 14)),
            ("Latmalt Minhenes Miežu Iesals (20,5 EBC)", (20.5, 20.5)),
            ("Château Whisky Light®, 25 ppm, 3 EBC Miežu iesals", (3, 3)),
            ("BestMalz Black malt (1100-1200 EBC)", (1100, 1200)),
        ],
    )
    def test_from_title(self, title, expected):
        low, high, source = parse_colour(title, "")
        assert (low, high) == expected and source == "title"

    def test_falls_back_to_description(self):
        low, high, source = parse_colour("Château Smoked Miežu Iesals", "Colour EBC: 3 – 12 and more")
        assert (low, high, source) == (3, 12, "desc")

    def test_unknown_when_absent(self):
        assert parse_colour("Rudzu Pārslas", "Rudzu pārslas cepšanai") is None

    def test_srm_conversion(self):
        assert ebc_to_srm(100) == 50.8
        assert ebc_to_srm(None) is None


class TestHop:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Alfa skābe 10%-15% (15,4%) Beta Skābe 3%-4.5%", (10, 15.4, 15.4)),
            ("Alfa skābe 12.1% Beta Skābe 4.0 – 5.0%", (12.1, 12.1, 12.1)),
            ("Alfa skābe 4%-6% (4,8%)", (4, 6, 4.8)),
            ("Alfa skābes: aptuveni 11–13% Aromāts", (11, 13, 12)),
            ("Alfa skābe 12 – 16% (16.9%)", (12, 16.9, 16.9)),
            ("Alfa skābe 8 % Beta Skābe 5%", (8, 8, 8)),
        ],
    )
    def test_alpha(self, text, expected):
        low, high, typical, source = parse_alpha(text)
        assert (low, high, typical) == expected and source == "desc"

    @pytest.mark.parametrize("text", ["", "alfa skābju līmeni – rūgtuma to izmanto reti", "alfa šķirne (6–7%)", "Alfa skābe 99%"])
    def test_alpha_unknown_not_guessed(self, text):
        assert parse_alpha(text) is None

    def test_title_parts(self):
        assert parse_hop_title("Spalter select T90 GER 2025") == {"hop_form": "T90", "origin": "DE", "title_year": 2025}
        assert parse_hop_title("Galaxy Apiņi T-90 AUS") == {"hop_form": "T90", "origin": "AUS", "title_year": None}
        assert parse_hop_title("Willamette apiņi T90 USA")["origin"] == "USA"


class TestYeast:
    @pytest.mark.parametrize(
        "title,brand,lab,code",
        [
            ("Fermentis SafAle US-05", None, "Fermentis", "US-05"),
            ("Fermentis SafLager W-34/70", None, "Fermentis", "W-34/70"),
            ("White Labs WLP001 California Ale 11g", None, "White Labs", "WLP001"),
            ("Mangrove Jack’s US West Coast M44 raugs, 10 g", "Mangrove Jack's", "Mangrove Jack's", "M44"),
            ("Lallemand WildBrew™ Philly Sour", None, "Lallemand", None),
            ("LALVIN Bourgovin RC212", "LALVIN", "Lalvin", "RC212"),
            ("Lalvin EC-1118", "LALVIN", "Lalvin", "EC-1118"),
            ("Lalvin ICV K1-V1116", "LALVIN", "Lalvin", "K1-V1116"),
            ("Lallemand LalBrew® CBC-1 – 11g", None, "Lallemand", "CBC-1"),
            ("Pinnacle English Ale", None, "Pinnacle", None),
        ],
    )
    def test_lab_and_code(self, title, brand, lab, code):
        detected = detect_lab(brand, title)
        assert detected == lab
        assert detect_code(title, detected) == code

    def test_form(self):
        assert detect_form("CellarScience® HEFE Sausais Alus Raugs 15 g", "CellarScience") == ("dry", "title")
        assert detect_form("White Labs WLP001 California Ale 11g", "White Labs") == ("dry", "inferred")
        assert detect_form("Wyeast 1056 šķidrais raugs", "Wyeast") == ("liquid", "title")

    def test_performance_labelled_lines(self):
        text = (
            "Rauga funkcijas: Fermentācijas temperatūra: 12–25°C, vislabāk 15-20°C Vājinājums: 72–78% "
            "Alkohola tolerance: 9-11% Flokulācija: augsta"
        )
        assert parse_performance(text) == {
            "att_min": 72, "att_max": 78, "floc": "high", "temp_min": 12, "temp_max": 25, "abv_tol": 11,
        }

    def test_performance_prose(self):
        text = "Ļoti augsta flokulācija (5/5) Augsta atšķaidīšana: 95–100 % Alkohola tolerance līdz 15 % ABV"
        parsed = parse_performance(text)
        assert parsed["floc"] == "very high" and parsed["att_min"] == 95 and parsed["abv_tol"] == 15

    def test_performance_floc_pair_and_temperature_phrase(self):
        parsed = parse_performance("Flokulācija: zema / vidēja Fermentācijas temperatūra: 15-24 ° C Devas: 50-80 g / hl")
        assert parsed["floc"] == "low-medium" and (parsed["temp_min"], parsed["temp_max"]) == (15, 24)
        assert parse_performance("labi fermentējas no 15°C līdz 38°C")["temp_max"] == 38

    def test_performance_ignores_unrelated_numbers(self):
        assert parse_performance("Devas: 50-100 g/hl. Derīguma termiņš 07.2025") == {}


class TestNormalize:
    def _product(self, **overrides):
        base = {
            "id": 1,
            "name": "Test &amp; Co",
            "permalink": "https://bruve.lv/veikals/x/",
            "type": "simple",
            "description": "",
            "prices": {"price": "190"},
            "categories": [{"id": 1, "slug": "iesali"}, {"id": 2, "slug": "karamelizets-iesals"}],
            "brands": [],
            "attributes": [],
            "is_in_stock": True,
            "add_to_cart": {"maximum": 61.2, "multiple_of": 0.1},
        }
        base.update(overrides)
        return base

    def test_malt_priced_per_kg_with_stock_quantity(self):
        record = normalize_product(self._product(name="BestMalz Caramel Aromatic (41-60 EBC)"))
        assert record["kind"] == "malt" and record["role"] == "caramel"
        assert record["sold_by"] == "kg" and record["stock_qty"] == 61.2 and record["price_cents"] == 190
        assert (record["ebc_min"], record["ebc_max"]) == (41, 60)

    def test_shop_ebc_attribute_is_ignored(self):
        attr = [{"name": "Ebc", "terms": [{"name": "30"}]}]
        record = normalize_product(self._product(name="Rudzu iesals", attributes=attr))
        assert "ebc_min" not in record

    def test_hop_attribute_alpha_is_kept_only_as_unverified_hint(self):
        product = self._product(
            name="Cascade Apiņi T90 USA",
            categories=[{"id": 3, "slug": "apini"}],
            attributes=[{"name": "Alfa Skābe", "terms": [{"name": "14"}]}],
            add_to_cart={"maximum": 9999, "multiple_of": 1},
        )
        record = normalize_product(product)
        assert "alpha" not in record and record["attr_alpha"] == "14" and record["stock_qty"] is None
