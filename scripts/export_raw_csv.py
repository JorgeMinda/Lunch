"""Exporta las 6 hojas del Excel fuente a CSV en data/raw/."""
import os
import pandas as pd

SRC = r"C:\Users\minda\Downloads\17-09-2026 REQ. COPIA MENU DESDE AGOSTO A JULIO 2026-2027 YUMISI.xlsx"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

NAMES = [
    "01_catalogo_insumos",
    "02_costeo_recetas_almuerzos",
    "03_menu_agosto_julio_2026_2027",
    "04_costeo_refrigerios",
    "05_menu_refrigerios",
    "06_composicion_cada_plato",
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    xl = pd.ExcelFile(SRC)
    assert len(xl.sheet_names) == 6, xl.sheet_names
    for name, stem in zip(xl.sheet_names, NAMES):
        df = xl.parse(name, header=None)
        path = os.path.join(OUT, f"{stem}.csv")
        df.to_csv(path, index=False, header=False, encoding="utf-8-sig")
        print(f"{stem}: {df.shape[0]} filas x {df.shape[1]} cols")


if __name__ == "__main__":
    main()
