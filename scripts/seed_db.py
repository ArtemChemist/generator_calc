"""One-time script to seed instance/generator.db from the radioactivedecay ICRP-107 dataset."""
import os
import sqlite3
import math
import radioactivedecay as rd

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'instance', 'generator.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS isotopes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL UNIQUE,
    name          TEXT,
    half_life_s   REAL NOT NULL,
    atomic_number INTEGER,
    mass_number   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_isotopes_symbol ON isotopes(symbol);

CREATE TABLE IF NOT EXISTS decay_modes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_symbol   TEXT NOT NULL,
    daughter_symbol TEXT NOT NULL,
    branching_ratio REAL NOT NULL DEFAULT 1.0,
    mode            TEXT
);

CREATE INDEX IF NOT EXISTS idx_decay_parent ON decay_modes(parent_symbol);

CREATE TABLE IF NOT EXISTS generator_presets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name    TEXT NOT NULL,
    parent_symbol   TEXT NOT NULL,
    daughter_symbol TEXT NOT NULL,
    sort_order      INTEGER DEFAULT 0
);
"""

PRESETS = [
    ('Ra-225 / Ac-225', 'Ra-225', 'Ac-225', 0),
    ('Mo-99 / Tc-99m',  'Mo-99',  'Tc-99m', 1),
    ('Sr-90 / Y-90',    'Sr-90',  'Y-90',   2),
    ('Ge-68 / Ga-68',   'Ge-68',  'Ga-68',  3),
    ('Rb-82 / Kr-82',   'Rb-82',  'Kr-82',  4),
    ('Sn-117m / In-117m', 'Sn-117m', 'In-117m', 5),
]


def symbol_to_name(symbol: str) -> str:
    """Convert 'Mo-99' → 'Molybdenum-99'."""
    try:
        n = rd.Nuclide(symbol)
        element_names = {
            1:'Hydrogen',2:'Helium',3:'Lithium',4:'Beryllium',5:'Boron',
            6:'Carbon',7:'Nitrogen',8:'Oxygen',9:'Fluorine',10:'Neon',
            11:'Sodium',12:'Magnesium',13:'Aluminium',14:'Silicon',15:'Phosphorus',
            16:'Sulfur',17:'Chlorine',18:'Argon',19:'Potassium',20:'Calcium',
            21:'Scandium',22:'Titanium',23:'Vanadium',24:'Chromium',25:'Manganese',
            26:'Iron',27:'Cobalt',28:'Nickel',29:'Copper',30:'Zinc',
            31:'Gallium',32:'Germanium',33:'Arsenic',34:'Selenium',35:'Bromine',
            36:'Krypton',37:'Rubidium',38:'Strontium',39:'Yttrium',40:'Zirconium',
            41:'Niobium',42:'Molybdenum',43:'Technetium',44:'Ruthenium',45:'Rhodium',
            46:'Palladium',47:'Silver',48:'Cadmium',49:'Indium',50:'Tin',
            51:'Antimony',52:'Tellurium',53:'Iodine',54:'Xenon',55:'Caesium',
            56:'Barium',57:'Lanthanum',58:'Cerium',59:'Praseodymium',60:'Neodymium',
            61:'Promethium',62:'Samarium',63:'Europium',64:'Gadolinium',65:'Terbium',
            66:'Dysprosium',67:'Holmium',68:'Erbium',69:'Thulium',70:'Ytterbium',
            71:'Lutetium',72:'Hafnium',73:'Tantalum',74:'Tungsten',75:'Rhenium',
            76:'Osmium',77:'Iridium',78:'Platinum',79:'Gold',80:'Mercury',
            81:'Thallium',82:'Lead',83:'Bismuth',84:'Polonium',85:'Astatine',
            86:'Radon',87:'Francium',88:'Radium',89:'Actinium',90:'Thorium',
            91:'Protactinium',92:'Uranium',93:'Neptunium',94:'Plutonium',95:'Americium',
            96:'Curium',97:'Berkelium',98:'Californium',99:'Einsteinium',100:'Fermium',
            101:'Mendelevium',102:'Nobelium',103:'Lawrencium',104:'Rutherfordium',
            105:'Dubnium',106:'Seaborgium',107:'Bohrium',108:'Hassium',109:'Meitnerium',
        }
        mass_part = symbol.split('-', 1)[1] if '-' in symbol else ''
        element = element_names.get(n.Z, f'Element-{n.Z}')
        return f'{element}-{mass_part}'
    except Exception:
        return symbol


def main():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    data = rd.DEFAULTDATA
    all_symbols = list(data.nuclide_dict.keys())

    isotope_rows = []
    for sym in all_symbols:
        sym = str(sym)
        try:
            n = rd.Nuclide(sym)
            hl = n.half_life('s')
            hl_s = 1e30 if (hl is None or math.isinf(hl)) else float(hl)
            isotope_rows.append((sym, symbol_to_name(sym), hl_s, int(n.Z), int(n.A)))
        except Exception:
            continue

    conn.executemany(
        'INSERT OR IGNORE INTO isotopes (symbol, name, half_life_s, atomic_number, mass_number) VALUES (?,?,?,?,?)',
        isotope_rows,
    )

    decay_rows = []
    for sym in all_symbols:
        sym = str(sym)
        try:
            n = rd.Nuclide(sym)
            daughters = n.progeny()
            fractions = n.branching_fractions()
            modes = n.decay_modes()
            for d, f, m in zip(daughters, fractions, modes):
                decay_rows.append((sym, str(d), float(f), str(m)))
        except Exception:
            continue

    conn.executemany(
        'INSERT INTO decay_modes (parent_symbol, daughter_symbol, branching_ratio, mode) VALUES (?,?,?,?)',
        decay_rows,
    )

    conn.executemany(
        'INSERT OR IGNORE INTO generator_presets (display_name, parent_symbol, daughter_symbol, sort_order) VALUES (?,?,?,?)',
        PRESETS,
    )

    conn.commit()

    n_iso = conn.execute('SELECT COUNT(*) FROM isotopes').fetchone()[0]
    n_decay = conn.execute('SELECT COUNT(*) FROM decay_modes').fetchone()[0]
    n_pre = conn.execute('SELECT COUNT(*) FROM generator_presets').fetchone()[0]
    conn.close()

    print(f'Seeded {n_iso} isotopes, {n_decay} decay modes, {n_pre} presets → {os.path.abspath(DB_PATH)}')


if __name__ == '__main__':
    main()
