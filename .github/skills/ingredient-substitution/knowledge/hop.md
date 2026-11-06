# Hop substitution groups
# status: DRAFT. Written from general brewing knowledge as relationships between named varieties. Not copied from, and
# not verified against, the reference sites; spot-check lines against them and flip the last column to `reviewed`.
# compare against: Grainfather hop substitution chart, Homebrewers Association hop substitutions
# (both blocked to scripts; open in a browser)
#
# line format: id | members (separated by ;) | tier | what changes | review
# tier: close = near drop-in | fair = same character family, noticeable difference | distant = last resort | never = do NOT swap
# tier describes how freely members trade places with each other. Rules that always apply:
#  - bittering additions (boil 15+ min): match alpha acid, not variety. Keep IBU by scaling grams by alpha ratio.
#  - aroma and dry-hop additions: match character; keep grams, adjust only if the oil level is clearly different.
# Search with: grep -i "<name>" knowledge/hop.md
#
H-NOBLE-CZ | Saaz; Žatec; Sladek; Saaz Latvia; Lublin; Lubelski | close | spicy, herbal, earthy; Sladek is a Saaz-type, Lublin is a close Polish relative; keep the same grams | draft
H-NOBLE-DE | Hallertauer Mittelfrüh; Hallertau Mittelfruh; Hallertau Tradition; Hallertauer Tradition; Hersbrucker; Hersbrucker Spät; Spalt; Spalter Select; Tettnang; Tettnanger; Hallertau Tettnanger; Saphir | fair | mild, floral, herbal and spicy; Mittelfrüh is the classic, Tradition and Hersbrucker are close, Spalter Select is a little more citrusy, Saphir leans lemony | draft
H-NOBLE-ALL | Saaz; Hallertauer Mittelfrüh; Tettnang; Spalt; Spalter Select; Sladek; Lublin; Hersbrucker | fair | any noble-type hop can fill a lager or pilsner aroma slot; expect small differences in spice versus floral | draft
H-ENGLISH | East Kent Goldings; EKG; Goldings; Fuggle; Fuggles; Styrian Golding; Styrian Goldings; Savinjski Golding; Willamette; Challenger | fair | earthy, woody, mild fruit; Willamette is the closest US relative of Fuggle, Styrian Golding sits between Fuggle and Goldings | draft
H-HALLERTAU-BLANC | Hallertau Blanc; Hallertauer Blanc; Hüll Melon; Mandarina Bavaria; Nelson Sauvin | fair | white wine, gooseberry and melon; Nelson Sauvin is the more intense and vinous, Mandarina leans orange, Hüll Melon honeydew | draft
H-CASCADE-FAMILY | Cascade; Centennial; Amarillo; Ahtanum; Cashmere; Dolcita | fair | citrus and floral; Centennial is stronger and more resinous (often called a super Cascade), Amarillo more orange and peach, Cascade the mildest | draft
H-DANK-CTZ | Columbus; Tomahawk; Zeus; CTZ; CTZ (Zeus); Zeus CTZ | close | these are the same hop family sold under three names; high alpha, dank and resinous | draft
H-PINE-RESIN | Simcoe; Chinook; Columbus; Idaho-7; Warrior; Apollo | fair | pine, resin and tropical; Simcoe and Idaho 7 are fruitier, Chinook and Columbus danker | draft
H-TROPICAL-US | Citra; Mosaic; Ekuanot; Equinox; El Dorado; Azacca; Idaho-7; Simcoe; Amarillo; Dolcita; Anchovy | fair | citrus, tropical and stone fruit; Citra and Mosaic are the usual stand-ins for each other, Ekuanot is dankier, El Dorado candy-like, Azacca mango | draft
H-SABRO | Sabro; Citra; Mosaic | distant | coconut, stone fruit and mint are unusual; the others give tropical fruit without the coconut | draft
H-NZ-TROPICAL | Nelson Sauvin; Motueka; Riwaka; Rakau; Nectaron; Pacifica; Kohatu; Wakatu; Superdelic; Wai-iti; Waimea | fair | New Zealand citrus, passion fruit and lime; Nelson is vinous, Motueka and Riwaka lime and passion fruit, Nectaron tropical, Pacifica and Wakatu gentler | draft
H-AUS | Galaxy; Ella; Vic Secret; Topaz; Enigma; Anchovy; Eclipse; Summer | fair | Australian passion fruit, pineapple and citrus; Galaxy is the most intense; Topaz is also often used for bittering | draft
H-AUS-GALAXY-US | Galaxy; Citra; Mosaic; Ella | distant | no true Galaxy stand-in; Citra plus a little Mosaic gets close to the passion fruit and citrus | draft
H-DRAGON | Styrian Dragon; Citra; Mandarina Bavaria; Azacca | distant | fruity Slovenian hop with a tropical and stone-fruit side; pick by the aroma needed | draft
H-BITTER-NEUTRAL | Magnum; Herkules; Hallertau Magnum; Warrior; Nugget; Columbus; Taurus; Polaris; Apollo | fair | clean, high alpha bittering hops; match the alpha and rescale grams; Herkules is a bit spicier, Columbus danker, Polaris minty | draft
H-BITTER-NOBLE | Perle; Hallertau Perle; Hallertauer Perle; Northern Brewer; Magnum; Hallertau Magnum; Tradition | fair | clean to lightly spicy bittering; Perle and Northern Brewer give a hint of mint, Magnum is neutral | draft
H-LILLY | Lilly; Spalter Select; Saaz; Hallertauer Mittelfrüh; Sladek | distant | Lilly is a low-key aromatic noble-style hop; no exact twin in the shop | draft
H-KOHATU | Kohatu; Citra; Motueka; Mosaic | distant | NZ hop with tropical, pine and herbal notes; no exact twin | draft
H-CASHMERE | Cashmere; Cascade; Centennial; Amarillo | fair | citrus and coconut; the Cascade family covers the citrus side | draft
H-HERKULES | Herkules; Magnum; Hallertau Magnum; Columbus | fair | high alpha German bittering with a slightly spicy edge | draft
H-FORMS | T90 pellets; Type 90; T-90; Pellets; T45; Cryo; Lupulin powder; Leaf hops; Whole cone | never | form changes utilisation: pellets use about 10% more than whole cone for the same alpha; cryo or lupulin pellets are roughly twice as potent by weight; never swap forms gram for gram | draft
