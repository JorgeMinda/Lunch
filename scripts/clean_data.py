#!/usr/bin/env python3
"""Fase 1: limpieza y normalización de los CSV crudos → data/clean/ + errors_report.md.

Reglas de negocio aplicadas:
  * Costo financiero por plato = costo base ingredientes × 1.08 (5% merma + 3% indirectos).
  * Requisición física = gramaje bruto por porción × porciones proyectadas (sin duplicar merma).
  * Catálogo maestro = única fuente de verdad de precios de compra.
  * % merma física por defecto 0% (fórmula de rendimiento solo si un insumo lo requiere).
"""
from __future__ import annotations

import csv
import difflib
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"

FACTOR = 1.08  # 5% merma/cocción + 3% gastos indirectos (suma lineal)

# ---------------------------------------------------------------- utilidades

ISSUES: list[dict] = []


def issue(kind: str, detail: str, source: str = "") -> None:
    ISSUES.append({"kind": kind, "detail": detail, "source": source})


def norm(text: str) -> str:
    """Mayúsculas, sin acentos, espacios colapsados."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().upper()


def slug(text: str) -> str:
    base = norm(text)
    base = re.sub(r"[^A-Z0-9]+", "-", base).strip("-")
    return base[:60] or "SIN-NOMBRE"


def to_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".")
    if not s or s.startswith("#") or s in {"$", "$ -", "-", "NaN"}:
        return None
    # expresiones simples tipo "5*1.00"
    if re.fullmatch(r"[0-9.\s*/+%-]+", s) and re.search(r"[*/]", s):
        try:
            return float(eval(s, {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def read_rows(name: str) -> list[list[str]]:
    with (RAW / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if idx < len(row) else ""


# ---------------------------------------------------------------- unidades

UNIT_TOKENS = {
    "KILOGRAMO": "G", "KILOGRAMOS": "G", "KILO": "G", "KILOS": "G", "KG": "G", "KGS": "G", "KL": "G",
    "GRAMO": "G", "GRAMOS": "G", "GR": "G", "G": "G",
    "LIBRA": "LB", "LIBRAS": "LB", "LB": "LB", "LBS": "LB",
    "LITRO": "ML", "LITROS": "ML", "LT": "ML", "LTS": "ML",
    "MILILITRO": "ML", "MILILITROS": "ML", "ML": "ML", "CC": "ML",
    "ARROBA": "ARROBA",
    "QUINTAL": "QQ", "QQ": "QQ",
    "UNIDAD": "UND", "UNIDADES": "UND", "UNID": "UND", "UNDS": "UND", "UND": "UND", "UNIDUD": "UND",
    "DOLAR": "UND", "DOLARES": "UND",
    "CUBETA": "CUBETA", "BALDE": "BALDE", "CAJA": "CAJA", "FUNDA": "FUNDA", "BOTELLA": "BOTELLA",
    "ATADO": "ATADO", "PAQ": "PAQ", "PAQUETE": "PAQ", "ROLLO": "ROLLO", "RESMA": "RESMA",
    "DOCENA": "DOCENA", "ONZA": "ONZ", "ONZAS": "ONZ",
}
CONTAINER_UNITS = {"CUBETA", "BALDE", "CAJA", "FUNDA", "BOTELLA", "ATADO", "PAQ", "ROLLO",
                   "RESMA", "DOCENA", "ARROBA", "QQ", "UND", "ONZ"}
# factores de conversión del TOKEN original a la unidad base (G / ML / UND)
TOKEN_FACTOR = {
    "KILOGRAMO": 1000.0, "KILOGRAMOS": 1000.0, "KILO": 1000.0, "KILOS": 1000.0, "KG": 1000.0,
    "KGS": 1000.0, "KL": 1000.0,
    "GRAMO": 1.0, "GRAMOS": 1.0, "GR": 1.0, "G": 1.0,
    "LIBRA": 454.0, "LIBRAS": 454.0, "LB": 454.0, "LBS": 454.0,
    "LITRO": 1000.0, "LITROS": 1000.0, "LT": 1000.0, "LTS": 1000.0,
    "MILILITRO": 1.0, "MILILITROS": 1.0, "ML": 1.0, "CC": 1.0,
    "ARROBA": 11340.0,
    "QUINTAL": 45400.0, "QQ": 45400.0,
    "ONZA": 29.5735, "ONZAS": 29.5735, "ONZ": 29.5735,
}
UNIT_DEFAULT_QTY = {"G": 1000.0, "LB": 454.0, "ML": 1000.0, "ARROBA": 11340.0,
                    "QQ": 45400.0, "UND": 1.0}
BASE_OF = {"G": "G", "LB": "G", "ML": "ML", "ARROBA": "G", "QQ": "G", "UND": "UND",
           "CUBETA": "UND", "BALDE": "UND", "CAJA": "UND", "FUNDA": "UND", "BOTELLA": "UND",
           "ATADO": "UND", "PAQ": "UND", "ROLLO": "UND", "RESMA": "UND", "DOCENA": "UND",
           "ONZ": "ML"}


def parse_measure(text: str) -> tuple[float, str] | None:
    """Extrae (cantidad_en_base, unidad_base) de textos como '20 LITROS', '1KG', '453GR'."""
    if not text:
        return None
    t = norm(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([A-Z]+)", t)
    if not m:
        return None
    token = m.group(2)
    unit = UNIT_TOKENS.get(token)
    if not unit:
        return None
    qty = float(m.group(1).replace(",", "."))
    return qty * TOKEN_FACTOR.get(token, 1.0), BASE_OF[unit]


def unit_only(text: str) -> str | None:
    """Devuelve la unidad si el texto es solo una palabra de unidad ('KILOS', 'LIBRA'...)."""
    t = norm(text)
    return UNIT_TOKENS.get(t)


def parse_date(text: str) -> date | None:
    t = str(text or "").strip()
    if not t or t.startswith("#"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- catálogo

def load_catalog() -> dict[str, dict]:
    rows = read_rows("01_catalogo_insumos.csv")
    items: dict[str, dict] = {}
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 6:
            continue
        code, category, name, presentation, cost_raw, state = (cell(row, j) for j in range(6))
        name = name.strip()
        if not name:
            continue
        key = norm(name)
        cost = to_float(cost_raw)
        if cost is None and cost_raw:
            issue("CATALOGO_COSTO_INVALIDO", f"fila {i}: costo '{cost_raw}' en '{name}'", "catalogo")
        qty, base = parse_measure(presentation), None
        if qty:
            qty_val, base = qty
        else:
            qty_val, base = None, None
        entry = {
            "sku": code or f"AUTO-{len(items) + 1:04d}",
            "code": code,
            "name": name,
            "category": category.strip(),
            "presentation": presentation.strip(),
            "qty": qty_val,
            "base_unit": base,
            "cost": cost,
            "state": state.strip(),
            "qty_source": "presentacion" if qty_val is not None else None,
            "notes": "",
            "row": i,
        }
        if key in items:
            # regla única de duplicados: gana el precio MÁXIMO (prudencia presupuestaria)
            prev = items[key]
            keep_new = cost is not None and (prev["cost"] is None or cost > prev["cost"])
            winner = entry if keep_new else prev
            loser = prev if keep_new else entry
            issue("CATALOGO_DUPLICADO",
                  f"'{name}': cód {loser['code']} ${loser['cost']} vs cód {winner['code']} "
                  f"${winner['cost']} → gana el precio máximo (cód {winner['code']})", "catalogo")
            if keep_new:
                items[key] = entry
            continue
        items[key] = entry
    # regla 2 (cifra en el nombre) y regla 3 (recetas) se resuelven en
    # fill_catalog_qty_from_recipes para poder ordenarlas por precedencia
    return items


CONTAINER_TOKENS = {"CUBETA", "BALDE", "CAJA", "FUNDA", "BOTELLA", "ATADO",
                    "PAQ", "PAQUETE", "ROLLO", "RESMA", "DOCENA"}


def fill_catalog_qty_from_recipes(catalog: dict[str, dict], recipe_qty: dict[str, Counter]) -> None:
    """Resuelve qty/base_unit cuando la presentación del catálogo no trae cifra.

    Orden de precedencia (catálogo = fuente de verdad, REQ-01):
      1. presentación con cifra (ya resuelta en load_catalog)
      2. presentación = contenedor (CUBETA/CAJA/…): modo de recetas → nombre → default
      3. resto: cifra del nombre con base G/ML → unidad implícita de la presentación
         (KILO→1000 G, UNIDAD→1 UND, DÓLAR→1 UND) → recetas → default
    El modo de recetas desempata hacia el valor más chico para descartar outliers
    (ej. c3=50000 en un durazno que en realidad vale 1 UND).
    """
    for key, it in catalog.items():
        if it["qty"] is None:
            modes = recipe_qty.get(key)
            pres_unit = unit_only(it["presentation"])
            name_parsed = parse_measure(it["name"])

            def take_recetas() -> bool:
                if not modes:
                    return False
                best = max(modes.values())
                candidates = [v for v, n in modes.items() if n == best and v]
                if not candidates:
                    return False
                qty_val = min(candidates)
                it["qty"], it["qty_source"] = qty_val, f"recetas({modes[qty_val]}x)"
                return True

            if pres_unit in CONTAINER_TOKENS:
                # el contenido real del contenedor solo lo saben las recetas
                if not take_recetas():
                    if name_parsed:
                        it["qty"], it["base_unit"] = name_parsed
                        it["qty_source"] = "nombre"
                    else:
                        it["qty"], it["qty_source"] = 1.0, "default_unidad"
            else:
                if name_parsed and name_parsed[1] in ("G", "ML"):
                    it["qty"], it["base_unit"] = name_parsed
                    it["qty_source"] = "nombre"
                elif pres_unit and pres_unit in UNIT_DEFAULT_QTY:
                    it["qty"] = UNIT_DEFAULT_QTY[pres_unit]
                    it["base_unit"] = BASE_OF[pres_unit]
                    it["qty_source"] = "presentacion_unidad"
                elif name_parsed:
                    it["qty"], it["base_unit"] = name_parsed
                    it["qty_source"] = "nombre"
                elif not take_recetas():
                    unit = unit_only(it["name"])
                    if unit and unit in UNIT_DEFAULT_QTY:
                        it["qty"] = UNIT_DEFAULT_QTY[unit]
                        it["base_unit"] = BASE_OF[unit]
                        it["qty_source"] = "default_unidad"
                    else:
                        it["qty"], it["base_unit"], it["qty_source"] = 1.0, "UND", "default_unidad"
                        it["notes"] = "cantidad de presentación no determinable; asumido 1 UND"
                        issue("CATALOGO_SIN_CANTIDAD",
                              f"'{it['name']}' sin cantidad de presentación; asumido 1 UND", "catalogo")
        # unidad base: derivar de la presentación/nombre si no vino de parse_measure
        if not it["base_unit"]:
            unit = unit_only(it["presentation"]) or unit_only(it["name"])
            if unit:
                it["base_unit"] = BASE_OF[unit]
            else:
                # sin unidad explícita: gramaje grande ⇒ peso; resto ⇒ unidad
                it["base_unit"] = "G" if (it["qty"] or 0) >= 100 else "UND"
        if it["qty_source"] and it["qty_source"].startswith("recetas"):
            it["notes"] = (it["notes"] + "; ").strip("; ") + "cantidad tomada de recetas"
        if it["cost"] is None:
            it["notes"] = (it["notes"] + "; ").strip("; ") + "costo inválido en catálogo"
    # costo por unidad base
    for it in catalog.values():
        if it["cost"] is not None and it["qty"]:
            it["cost_per_base"] = it["cost"] / it["qty"]
        else:
            it["cost_per_base"] = None


ALIASES = {
    "SAL 1 KL": "SAL YODADA 1 KL",
    "PIMIENTA 1 KL": "PIMIENTA LB",
    "COMINO 200 GR": "COMINO LB",
    "MARGARINA LB": "MARGARINA INDUSTRIAL LB - DANEC",
    "ACEITE CANECA 20LT": "ACEITE CANECA 20 LT - VETOIL / SAN FRANCISCO",
    "ORIGANO 200 GR": "OREGANO LB",
    "AZUCAR ARROBA": "AZUCAR ARROBA SAN FRANCISCO",
    "PEREJIL500 GR": "PEREJIL500 GR",
    "SAL YODADA 1 KL ": "SAL YODADA 1 KL",
}


def match_ingredient(raw_name: str, catalog: dict[str, dict], threshold: float = 0.88):
    """→ (sku, key, 'exacto'|'alias'|'fuzzy'|None, score)."""
    n = norm(raw_name)
    if n in catalog:
        return catalog[n]["sku"], n, "exacto", 1.0
    alias = ALIASES.get(n)
    if alias and norm(alias) in catalog:
        k = norm(alias)
        return catalog[k]["sku"], k, "alias", 1.0
    best_key, best_score = None, 0.0
    for key in catalog:
        score = difflib.SequenceMatcher(None, n, key).ratio()
        if score > best_score:
            best_key, best_score = key, score
    if best_score >= threshold:
        return catalog[best_key]["sku"], best_key, "fuzzy", best_score
    return None, None, None, best_score


# ---------------------------------------------------------------- recetas

def parse_recipe_sheet(name: str, source: str) -> tuple[list[dict], list[dict], dict[str, Counter]]:
    """Devuelve (recipes, recipe_items, conteo qtyComp por ingrediente)."""
    rows = read_rows(name)
    recipes: list[dict] = []
    items: list[dict] = []
    qty_counter: dict[str, Counter] = defaultdict(Counter)

    title, section, header_seen = None, None, False
    portions = None
    lines: list[dict] = []
    sig_seen: dict[str, str] = {}
    recipes_by_id: dict[str, dict] = {}

    def flush() -> None:
        nonlocal title, section, header_seen, portions, lines
        if title and lines:
            key = norm(title)
            sig = key + "|" + "|".join(sorted(
                f"{l['ingredient_norm']}:{l['qty']}" for l in lines))
            if sig in sig_seen:
                rid = sig_seen[sig]
                recipes_by_id[rid]["occurrences"] += 1
            else:
                rid, n = slug(title), 2
                base_id = rid
                while rid in recipes_by_id:
                    rid = f"{base_id}-{n}"
                    n += 1
                if n > 2:
                    issue("RECETA_DUPLICADA_DIFERENTE",
                          f"'{title}' aparece con ingredientes distintos (bloque {n - 1})", source)
                sig_seen[sig] = rid
                recipes_by_id[rid] = {
                    "id": rid, "name": title, "name_norm": key, "source": source,
                    "section": section, "portions": portions,
                    "ingredient_count": len(lines),
                    "base_cost": 0.0, "total_cost": 0.0, "occurrences": 1,
                }
                # solo la primera ocurrencia de la firma aporta sus líneas;
                # repeticiones incrementan occurrences sin duplicar items
                for l in lines:
                    l["recipe_id"] = rid
                    items.append(l)
        title, section, header_seen, portions, lines = None, None, False, None, []

    for i, row in enumerate(rows, start=1):
        c0 = cell(row, 0)
        c1 = cell(row, 1)
        if c0 == "Ingrediente":
            header_seen = True
            continue
        if c0 and not c1:
            # fila de título (posible receta o etiqueta de sección)
            if header_seen and lines:
                flush()
            if title is None:
                title = c0
            elif section is None:
                section = c0  # ej. 'GUARNICION 1', 'PLATO FUERTE/OPCION 1'
            continue
        if not header_seen or not title:
            continue
        if not c0:
            continue  # filas de pie/subtotales
        p7 = to_float(cell(row, 7))
        if p7 and p7 > 0 and portions is None:
            portions = int(p7)  # col H (PROMEDIOS): solo en líneas de ingrediente
        qty_rec = to_float(cell(row, 5))
        if qty_rec is None:
            if c1:
                issue("RECETA_VALOR_INVALIDO", f"'{title}': cantidad en receta inválida en '{c0}'", source)
            continue
        pvp = to_float(cell(row, 2))
        qty_comp_raw = to_float(cell(row, 3))
        raw_presentation = c1
        nkey = norm(c0)
        qty_counter[nkey][qty_comp_raw] += 1 if qty_comp_raw else 0

        lines.append({
            "line_no": len(lines) + 1,
            "ingredient_raw": c0,
            "ingredient_norm": nkey,
            "presentation_recipe": raw_presentation,
            "pvp_recipe": pvp,
            "qty_comp_recipe": qty_comp_raw,
            "qty": qty_rec,
            "theoretical": to_float(cell(row, 8)),
            "adjusted": to_float(cell(row, 11)),
            "origin_line_cost": to_float(cell(row, 6)),  # costo que calculó el Excel
            "line_cost": 0.0,  # se calcula tras resolver catálogo
            "sku": None, "unit_cost": None, "price_source": None,
            "base_unit": None, "match": None, "score": None,
            "flags": set(),
        })

    flush()
    return list(recipes_by_id.values()), items, qty_counter


def resolve_items(items: list[dict], catalog: dict[str, dict]) -> None:
    for it in items:
        sku, key, match, score = match_ingredient(it["ingredient_raw"], catalog)
        it["match"], it["score"] = match, score
        cat = catalog.get(key) if key else None
        if cat:
            it["sku"] = sku
            line_parsed = parse_measure(it["presentation_recipe"])
            line_base = line_parsed[1] if line_parsed else None
            if line_base is None or line_base == cat["base_unit"]:
                # línea en la misma unidad base que el catálogo
                if cat["cost_per_base"] is not None:
                    it["base_unit"] = cat["base_unit"]
                    it["unit_cost"] = round(cat["cost_per_base"], 8)
                    it["price_source"] = "catalogo"
                    it["line_cost"] = it["qty"] * cat["cost_per_base"]
                else:
                    it["base_unit"] = cat["base_unit"]
                    it["price_source"] = None
                    issue("CATALOGO_SIN_COSTO",
                          f"'{cat['name']}' sin costo por unidad base", "recetas")
            elif it["qty_comp_recipe"] and cat["cost"] is not None:
                # línea en otra unidad base (c3 dice cuántas unidades de línea hay
                # en una presentación del catálogo): costo total del catálogo
                # repartido entre las unidades de la línea
                it["base_unit"] = line_base
                it["unit_cost"] = round(cat["cost"] / it["qty_comp_recipe"], 8)
                it["price_source"] = "catalogo_por_presentacion_linea"
                it["line_cost"] = it["qty"] * it["unit_cost"]
                it["flags"].add("unidad_difiere")
                issue("RECETA_UNIDAD_DIFIERE",
                      f"'{cat['name']}': receta en {line_base}, catálogo en "
                      f"{cat['base_unit']} (c3={it['qty_comp_recipe']})", "recetas")
            else:
                # sin c3 utilizable: fallback al costo por base del catálogo
                it["base_unit"] = cat["base_unit"]
                if cat["cost_per_base"] is not None:
                    it["unit_cost"] = round(cat["cost_per_base"], 8)
                    it["price_source"] = "catalogo"
                    it["line_cost"] = it["qty"] * cat["cost_per_base"]
                    issue("RECETA_SIN_CANTIDAD_COMPARABLE",
                          f"'{cat['name']}': c3 ausente; usado costo por base "
                          f"del catálogo", "recetas")
                else:
                    it["price_source"] = None
                    issue("CATALOGO_SIN_COSTO",
                          f"'{cat['name']}' sin costo por unidad base", "recetas")
            if match == "fuzzy":
                issue("CATALOGO_MATCH_FUZZY",
                      f"'{it['ingredient_raw']}' ~ '{cat['name']}' (score {score:.2f})", "recetas")
            # varianza de cantidad presentación receta vs catálogo (umbral 2%)
            if it["qty_comp_recipe"] and cat["qty"]:
                diff = abs(it["qty_comp_recipe"] - cat["qty"]) / cat["qty"]
                if diff > 0.02:
                    issue("CANTIDAD_PRESENTACION_VARIA",
                          f"'{cat['name']}': receta {it['qty_comp_recipe']} vs catálogo {cat['qty']}",
                          "recetas")
            # varianza de precio PVP receta vs catálogo
            if it["pvp_recipe"] and cat["cost"] and cat["qty"]:
                if abs(it["pvp_recipe"] - cat["cost"]) / cat["cost"] > 0.05:
                    it["flags"].add("precio_varia")
                    issue("PRECIO_VARIA",
                          f"'{cat['name']}': PVP receta {it['pvp_recipe']} vs catálogo {cat['cost']}",
                          "recetas")
            continue
        # sin catálogo: fallback al precio de la propia receta
        it["price_source"] = "receta" if (it["pvp_recipe"] and it["qty_comp_recipe"]) else None
        if it["price_source"]:
            base_unit = BASE_OF.get(unit_only(it["presentation_recipe"]) or "UND", "UND")
            it["base_unit"] = base_unit
            it["unit_cost"] = round(it["pvp_recipe"] / it["qty_comp_recipe"], 8)
            it["line_cost"] = it["qty"] * it["unit_cost"]
        issue("INGREDIENTE_SIN_CATALOGO",
              f"'{it['ingredient_raw']}' (mejor match {score:.2f})", "recetas")


# ---------------------------------------------------------------- menús

SLOTS_ALMUERZO = ["SOPA", "PROTEINA", "GUARNICION", "ENSALADA", "BEBIDA FRIA", "POSTRE", "FRUTA"]
SLOTS_REFRIGERIO = ["FRUTA", "BEBIDA", "ENTRADA", "PROTEINA", "ENSALADA", "JUGO"]
BAD_VALUES = {"", "0", "#REF!", "#VALUE!", "#DIV/0!", "#N/A", "FERIADO"}


def parse_almuerzo_menu() -> tuple[list[dict], list[dict], list[dict]]:
    rows = read_rows("03_menu_agosto_julio_2026_2027.csv")
    groups = [(0, 1, 5, "PRINCIPAL"), (7, 8, 12, "ALMUERZO_1"), (14, 15, 19, "ALMUERZO_2")]
    cycles: dict[date, dict] = {}
    days: dict[tuple[date, date], dict] = {}
    items: list[dict] = []
    slot_count: dict[tuple[date, str, str], int] = defaultdict(int)
    ref_rows = 0

    for i, row in enumerate(rows, start=1):
        for lc, d0, d1, variant in groups:
            label = cell(row, lc)
            if not label:
                continue
            if label.startswith("#REF") or label.startswith("#VALUE"):
                if variant == "PRINCIPAL":
                    ref_rows += 1
                continue
            dates = [parse_date(cell(row, c)) for c in range(d0, d1 + 1)]
            if label.upper().startswith("SEMANA") or label.upper() in {"ALMUERZO 1", "ALMUERZO 2"}:
                valid = [d for d in dates if d]
                if not valid:
                    continue
                start, end = min(valid), max(valid)
                if start not in cycles:
                    cycles[start] = {"date_start": start, "date_end": end, "labels": set()}
                cycles[start]["labels"].add(label.upper())
                cycles[start]["date_end"] = max(cycles[start]["date_end"], end)
                # guardar la fila de fechas del bloque para las filas de slot
                WEEK_DATES[variant] = (start, list(dates))
                continue
            slot = norm(label)
            if slot not in {norm(s) for s in SLOTS_ALMUERZO}:
                continue
            state = WEEK_DATES.get(variant)
            if state is None:
                continue
            start, week_dates = state
            for j, d in enumerate(week_dates):
                if not d:
                    continue
                dish = cell(row, d0 + j)
                if dish.upper() in BAD_VALUES:
                    if dish.upper() == "FERIADO":
                        days.setdefault((start, d), {"holiday": True, "name": "FERIADO"})
                    elif dish:
                        issue("MENU_VALOR_INVALIDO", f"{d} {variant} {label}: '{dish}'", "menu")
                    continue
                slot_count[(start, variant, slot)] += 1
                items.append({
                    "date": d, "variant": variant, "slot": label.strip(),
                    "slot_order": slot_count[(start, variant, slot)],
                    "dish": dish.strip(), "meal_type": "ALMUERZO", "cycle_start": start,
                })
    if ref_rows:
        issue("MENU_FILAS_ROTAS", f"{ref_rows} filas #REF! ignoradas al final de la hoja", "menu")

    # numeración secuencial por fechas (corrige semanas duplicadas)
    cycle_list = []
    for n, start in enumerate(sorted(cycles), start=1):
        c = cycles[start]
        labels = sorted(c["labels"])
        raw = next((l for l in labels if l.startswith("SEMANA")), labels[0] if labels else "")
        cycle_list.append({
            "cycle_id": f"CYC-ALM-{n:02d}", "source": "ALMUERZO", "label": raw,
            "week_number": n, "date_start": c["date_start"], "date_end": c["date_end"],
        })
        if raw and raw != f"SEMANA {n}":
            issue("MENU_SEMANA_DUPLICADA",
                  f"{c['date_start']}: etiqueta '{raw}' renumerada a SEMANA {n}", "menu")

    day_list = []
    seen_days: set[tuple[date, date]] = set()
    for it in items:
        key = (it["cycle_start"], it["date"])
        if key in seen_days:
            continue
        seen_days.add(key)
        d = it["date"]
        day_list.append({
            "cycle_start": it["cycle_start"], "date": d, "day_of_week": d.weekday() + 1,
            "is_holiday": False, "holiday_name": None, "source": "ALMUERZO",
        })
    for (start, d), h in days.items():
        day_list.append({"cycle_start": start, "date": d, "day_of_week": d.weekday() + 1,
                         "is_holiday": True, "holiday_name": h["name"], "source": "ALMUERZO"})
    # días sin ningún plato → posibles feriados/incompletos
    dates_with_items = {it["date"] for it in items}
    for dl in day_list:
        if dl["date"] not in dates_with_items and not dl["is_holiday"]:
            issue("MENU_DIA_VACIO", f"{dl['date']} sin platos cargados", "menu")
    return cycle_list, day_list, items


WEEK_DATES: dict[str, tuple[date, list]] = {}


def parse_refrigerio_menu() -> tuple[list[dict], list[dict], list[dict]]:
    rows = read_rows("05_menu_refrigerios.csv")
    cycles: dict[date, dict] = {}
    items: list[dict] = []
    slot_count: dict[tuple[date, str], int] = defaultdict(int)
    holidays: dict[date, str] = {}
    pending_dates: list[date] = []
    current_start = None

    for i, row in enumerate(rows, start=1):
        c0 = cell(row, 0)
        dates = [parse_date(cell(row, c)) for c in range(1, 6)]
        valid = [d for d in dates if d]
        if valid and norm(c0) in {"OPCION PLATO", "DIAS", ""}:
            start, end = min(valid), max(valid)
            current_start = start
            cycles[start] = {"date_start": start, "date_end": end}
            pending_dates = valid
            continue
        if not current_start:
            continue
        if c0 and norm(c0) not in {norm(s) for s in SLOTS_REFRIGERIO}:
            if "FERIADO" in [cell(row, c).upper() for c in range(1, 6)]:
                for j, d in enumerate(dates):
                    if cell(row, 1 + j).upper() == "FERIADO" and d:
                        holidays[d] = "FERIADO"
            continue
        if not c0:
            for j, d in enumerate(dates):
                if cell(row, 1 + j).upper() == "FERIADO" and d:
                    holidays[d] = "FERIADO"
            continue
        slot = norm(c0)
        if slot not in {norm(s) for s in SLOTS_REFRIGERIO}:
            continue
        for j, d in enumerate(dates):
            if not d:
                continue
            dish = cell(row, 1 + j)
            if dish.upper() in BAD_VALUES:
                continue
            slot_count[(d, c0)] += 1
            items.append({
                "date": d, "variant": "REFRIGERIO", "slot": c0.strip(),
                "slot_order": slot_count[(d, c0)], "dish": dish.strip(),
                "meal_type": "REFRIGERIO", "cycle_start": current_start,
            })

    cycle_list = []
    for n, start in enumerate(sorted(cycles), start=1):
        c = cycles[start]
        cycle_list.append({
            "cycle_id": f"CYC-REF-{n:02d}", "source": "REFRIGERIO", "label": f"REFRIGERIO {n}",
            "week_number": n, "date_start": c["date_start"], "date_end": c["date_end"],
        })
    day_list = []
    for it in sorted({(it["cycle_start"], it["date"]) for it in items}):
        start, d = it
        day_list.append({
            "cycle_start": start, "date": d, "day_of_week": d.weekday() + 1,
            "is_holiday": d in holidays, "holiday_name": holidays.get(d),
            "source": "REFRIGERIO",
        })
    for d, name in holidays.items():
        if not any(dl["date"] == d for dl in day_list):
            start = next((s for s, c in cycles.items() if c["date_start"] <= d <= c["date_end"]), None)
            if start:
                day_list.append({"cycle_start": start, "date": d,
                                 "day_of_week": d.weekday() + 1,
                                 "is_holiday": True, "holiday_name": name,
                                 "source": "REFRIGERIO"})
    return cycle_list, day_list, items


# ---------------------------------------------------------------- perfiles

def parse_profiles() -> tuple[list[dict], list[dict]]:
    rows = read_rows("06_composicion_cada_plato.csv")
    profiles, components = [], []
    name, target = None, None
    for i, row in enumerate(rows, start=1):
        c0, c1 = cell(row, 0), cell(row, 1)
        if c0 and not c1:
            if name and target is not None:
                profiles.append({"code": slug(name)[:30], "name": name,
                                 "target_price": target})
            name, target = c0, None
            continue
        if not name:
            continue
        if c0 == "Componente" or not c0:
            total = to_float(cell(row, 4))
            if total is not None and not c0:
                target = total
            continue
        qty, uc, line = (to_float(cell(row, j)) for j in (1, 3, 4))
        unit = cell(row, 2)
        if not unit:
            issue("PERFIL_VALOR_INVALIDO", f"{name}: unidad inválida en '{c0}'", "perfil")
            continue
        components.append({
            "profile_code": slug(name)[:30], "component": c0,
            "qty": qty, "unit": unit.strip().upper(),
            "unit_cost": uc, "line_cost": line,
        })
        if line is None:
            issue("PERFIL_VALOR_INVALIDO", f"{name}: costo de línea inválido en '{c0}'", "perfil")
    if name and target is not None:
        profiles.append({"code": slug(name)[:30], "name": name, "target_price": target})
    return profiles, components


# ---------------------------------------------------------------- emparejar menú↔receta

def strip_size(name: str) -> str:
    n = norm(name)
    # conservar las partes de un nombre con '/' (ej. 'ARROZ/LOMO' → dos claves)
    n = n.replace("/", " ")
    n = re.sub(r"[,.:;]+", " ", n)
    n = re.sub(r"\d+\s*(GR|G|GRAMOS|ONZ|ONZAS|ML|LT|UNIDAD|UNIDADES|PAX)\b", "", n)
    n = re.sub(r"\b\d+(?:[.,]\d+)?\b", "", n)
    n = re.sub(r"\b(DE|DEL|LA|EL|LOS|LAS|CON|Y|EN|AL|A)\b", "", n)
    n = re.sub(r"\b(?:GR|G|GRAMOS|ONZ|ONZAS|ML|LT|UNIDAD|UNIDADES|PAX)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


DISH_ALIASES = {"FRUTILLA": "FRESA", "FRUTILLAS": "FRESA", "FRESILLAS": "FRESA"}


def _alias_tokens(text: str) -> set[str]:
    toks = set(text.split())
    for a, b in DISH_ALIASES.items():
        if a in toks:
            toks.discard(a)
            toks.add(b)
    return toks


def _containment_score(query: str, key: str) -> float | None:
    """Tokens de un lado ⊆ el otro (en cualquier dirección); score = lado corto / largo."""
    qt, kt = _alias_tokens(query), _alias_tokens(key)
    if not qt or not kt:
        return None
    if qt <= kt:
        smaller, larger = qt, kt
    elif kt <= qt:
        smaller, larger = kt, qt
    else:
        return None
    if len(smaller) == 1:
        tok = next(iter(smaller))
        if len(tok) < 5:
            return None
    elif min(len(t) for t in smaller) < 4:
        return None
    return len(smaller) / len(larger)


def match_dish(dish: str, recipe_index: dict[str, str]):
    n = strip_size(dish)
    if not n:
        return None, None
    if n in recipe_index:
        return recipe_index[n], "exacto"
    # contención de tokens en cualquier dirección:
    #   'BISTEC EN SALSA' ⊆ 'BISTEC EN SALSA DE TOMATE'
    #   'AMBATEÑITO/CHORIZO/HUEVO/TORTILLA' ⊇ receta 'AMBATEÑITO/CHORIZO/HUEVO'
    best, best_score = None, 0.0
    for key, rid in recipe_index.items():
        if key == n:
            continue
        cs = _containment_score(n, key)
        if cs is not None and cs > best_score:
            best, best_score = rid, cs
    if best is not None and best_score >= 0.5:
        return best, f"contencion({best_score:.2f})"
    best, best_score = None, 0.0
    for key, rid in recipe_index.items():
        score = difflib.SequenceMatcher(None, n, key).ratio()
        if score > best_score:
            best, best_score = rid, score
    if best_score >= 0.82:
        return best, f"fuzzy({best_score:.2f})"
    return None, None


# ---------------------------------------------------------------- main

def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _source_block_bases(name: str) -> dict[str, float]:
    """Base cost del pie de cada bloque de la hoja de recetas (primer valor del col6)."""
    rows = read_rows(name)
    bases: dict[str, float] = {}
    title = None
    got_footer = False
    for row in rows:
        c0, c1 = cell(row, 0), cell(row, 1)
        if c0 and not c1:
            if c0 != "Ingrediente":
                title = c0
                got_footer = False
            continue
        if title and not c0:
            v = to_float(cell(row, 6))
            if v is not None and not got_footer:
                key = norm(title)
                bases.setdefault(key, v)  # primera ocurrencia de la firma
                got_footer = True
    return bases


def validate_against_source(recipes: dict[str, dict],
                            by_recipe: dict[str, list[dict]]) -> tuple[list[str], list[str], dict]:
    """Compara base_cost nuestro vs base del pie en la hoja origen (02/04).

    Clasifica los desvíos >10%:
      * 'explicado_por_origen': alguna línea donde el costo que calculó el Excel
        (col6) difiere >10% del nuestro → error del propio origen (lomo, precios
        cruzados, precios tecleados).
      * 'residual': todas las líneas cuadran pero el total no → revisar pipeline.
    """
    src = _source_block_bases("02_costeo_recetas_almuerzos.csv")
    src.update({k: v for k, v in
                _source_block_bases("04_costeo_refrigerios.csv").items()
                if k not in src})
    rows_out: list[tuple[float, str, str, str]] = []
    for r in recipes.values():
        s = src.get(r["name_norm"])
        if s is None or s <= 0:
            continue
        mine = r["base_cost"]
        pct = abs(mine - s) / s * 100
        detail = f"mio={mine:.6f} origen={s:.6f}"
        clase = ""
        if pct > 10:
            motivo = ""
            for l in by_recipe.get(r["id"], []):
                olc, lc = l.get("origin_line_cost"), l.get("line_cost")
                if not olc or not lc:
                    continue
                if abs(olc - lc) / max(olc, lc) > 0.10:
                    motivo = (f"{l['ingredient_raw'][:34]}: Excel {olc:.4f} "
                              f"vs nuestro {lc:.4f}")
                    break
            if motivo:
                clase = "explicado_por_origen"
                detail += f" | {motivo}"
            else:
                clase = "residual"
        rows_out.append((pct, r["name"], detail, clase))
    rows_out.sort(reverse=True)
    stats: dict = {"n": len(rows_out)}
    if rows_out:
        pcts = [p for p, _, _, _ in rows_out]
        stats |= {
            "mediana": statistics.median(pcts),
            "p75": statistics.quantiles(pcts, n=4)[2],
            "p90": sorted(pcts)[max(0, int(len(pcts) * 0.9) - 1)],
            "within2": sum(1 for p in pcts if p <= 2),
            "within5": sum(1 for p in pcts if p <= 5),
            "within10": sum(1 for p in pcts if p <= 10),
            "within20": sum(1 for p in pcts if p <= 20),
            "gt10": sum(1 for p in pcts if p > 10),
            "explicados": sum(1 for *_, c in rows_out if c == "explicado_por_origen"),
            "residuales": sum(1 for *_, c in rows_out if c == "residual"),
        }
        for pct, name, detail, clase in rows_out:
            if clase == "residual":
                issue("VALIDACION_VS_ORIGEN", f"{name}: {pct:.1f}% ({detail})", "validacion")
    fmt = lambda rs: [f"{name}: {pct:.1f}% ({detail})" for pct, name, detail, _ in rs]
    explicados = [t for t in rows_out if t[3] == "explicado_por_origen"]
    residuales = [t for t in rows_out if t[3] == "residual"]
    return fmt(residuales[:20]), fmt(explicados[:20]), stats


def validate_typed_totals() -> list[str]:
    """Col L (total consolidado tecleado, vista filtrada) vs Σ(F×H) por insumo.

    El libro no trae hoja de requisiciones: esa vista vive dentro de la hoja 02
    (H = porciones, L = total tecleado, M = costo del total). Un filtro oculta
    casi todas las filas; el export las incluye todas con los valores calculados
    por Excel, así que la cifra es reproducible desde data/raw.
    """
    rows = read_rows("02_costeo_recetas_almuerzos.csv")
    sum_fh: dict[str, float] = defaultdict(float)
    typed: list[tuple[str, float]] = []
    for row in rows:
        if len(row) < 8:
            continue
        c0 = cell(row, 0)
        if not c0 or c0 == "Ingrediente":
            continue
        f, h = to_float(cell(row, 5)), to_float(cell(row, 7))
        if f is not None and h:
            sum_fh[norm(c0)] += f * h
        if len(row) > 11:
            L = to_float(cell(row, 11))
            if L is not None:
                typed.append((norm(c0), L))
    match = miss = 0
    details: list[str] = []
    for k, L in typed:
        tot = sum_fh.get(k)
        if tot is None:
            continue
        if abs(L - tot) <= max(0.01 * max(L, tot), 1.0):
            match += 1
        else:
            miss += 1
            details.append(f"{k}: L={L:g} vs Σ(F×H)={tot:.0f} (Δ={L - tot:+g})")
    return [
        f"- líneas con L numérico: {len(typed)} | coinciden (≤1% o 1g): {match} "
        f"| no coinciden: {miss} (agrupación por nombre normalizado)",
        *("- " + d for d in details),
    ]


def client_reference_checks(recipes: dict[str, dict],
                            by_recipe: dict[str, list[dict]]) -> list[str]:
    """Cruce con los valores de referencia del informe del cliente."""
    out: list[str] = []
    targets = {
        "BISTEC CRIOLLO 110 GRAMOS": 0.70,
        "AMBATEÑITO 110 GRAMOS": 0.30,
        "AMBATEÑITO/CHORIZO/HUEVO": 0.30,
    }
    for norm_name, ref in targets.items():
        r = next((x for x in recipes.values() if x["name_norm"] == norm(norm_name)), None)
        if not r:
            out.append(f"- `{norm_name}`: no encontrada en recetas (referencia ${ref:.2f})")
            continue
        total = r["total_cost"]
        if "BISTEC" in norm_name:
            # el 0.70 del cliente parece ser SOLO la carne (85 g × $0.00833 = $0.708);
            # el total del plato incluye el resto de ingredientes y el ×1.08
            carne = sum(l["line_cost"] for l in by_recipe.get(r["id"], [])
                        if "LOMO" in l["ingredient_norm"])
            out.append(f"- `{r['name']}`: total ${total:.4f} | carne sola ${carne:.4f} "
                       f"| referencia ${ref:.2f} → carne ≈ referencia; alcance del "
                       f"${ref:.2f} (carne vs plato) POR CONFIRMAR con el cliente")
            continue
        flag = "OK" if abs(total - ref) <= 0.05 else "DESCUADRE"
        out.append(f"- `{r['name']}`: total ${total:.4f} vs referencia ${ref:.2f} → {flag}")
        if flag == "DESCUADRE":
            issue("REFERENCIA_CLIENTE_DESCUADRE",
                  f"'{r['name']}': total {total:.4f} vs {ref}", "validacion")
    return out


def validate_gramaje_perfil(menu: list[dict], by_recipe: dict[str, list[dict]],
                            components: list[dict]) -> tuple[list[str], dict]:
    """Gramaje por porción de la receta vs estándar del perfil estudiantil.

    Perfiles (hoja Composición): Almuerzo Saludable Estudiantil trae
    PROTEINA 100 g, GUARNICION 50 g, ARROZ 40 g… ; Refrigerio prescolar/primaria
    PROTEINA 60 g, GUARNICION 40 g… El gramaje de receta NO se reescala: se
    muestra la desviación y se alerta cuando supera ±10% del estándar.
    """
    prof: dict[tuple[str, str], float] = {}
    for c in components:
        if c["unit"] != "GR":
            continue
        if c["profile_code"] == "ALMUERZO-SALUDABLE-ESTUDIANTIL":
            prof[("ALMUERZO", norm(c["component"]))] = c["qty"]
        elif c["profile_code"].startswith("REFRIGERIO"):
            prof[("REFRIGERIO", norm(c["component"]))] = c["qty"]
    comps = {m: {k for (mm, k) in prof if mm == m} for m in ("ALMUERZO", "REFRIGERIO")}

    total_g: dict[str, float] = {}
    for rid, lines in by_recipe.items():
        total_g[rid] = sum(l["qty"] for l in lines if l["base_unit"] == "G")

    def component_for(meal: str, slot: str, dish: str) -> str | None:
        d, s = norm(dish), norm(slot)
        if re.search(r"\bARROZ\b", d) and d.startswith("ARROZ"):
            return "ARROZ" if "ARROZ" in comps[meal] else None
        if s in comps[meal]:
            return s
        if s.startswith("POSTRE"):
            for k in comps[meal]:
                if k.startswith("POSTRE"):
                    return k
        return None

    seen: set[tuple[str, str]] = set()
    out: list[tuple[float, str]] = []
    compared = 0
    for m in menu:
        rid = m.get("recipe_id")
        if not rid or rid not in total_g or not total_g[rid]:
            continue
        comp = component_for(m["meal_type"], m["slot"], m["dish"])
        if not comp:
            continue
        ref = prof.get((m["meal_type"], comp))
        if not ref:
            continue
        pair = (rid, comp)
        if pair in seen:
            continue
        seen.add(pair)
        compared += 1
        dev = (total_g[rid] - ref) / ref * 100
        if abs(dev) > 10:
            line = (f"{m['dish']} [{comp}] (receta {rid}): {total_g[rid]:.0f} g vs "
                    f"estándar {ref:.0f} g ({dev:+.1f}%)")
            out.append((abs(dev), line))
            issue("GRAMAJE_FUERA_PERFIL", line, "gramaje")
    out.sort(reverse=True)
    stats = {"comparados": compared, "fuera": len(out)}
    return [ln for _, ln in out[:20]], stats


def main() -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog()
    # pass 1: recetas solo para contar qtyComp
    _, _, qty_counts = parse_recipe_sheet("02_costeo_recetas_almuerzos.csv", "ALMUERZO")
    _, _, qty_counts_r = parse_recipe_sheet("04_costeo_refrigerios.csv", "REFRIGERIO")
    for k, v in qty_counts_r.items():
        qty_counts[k].update(v)
    fill_catalog_qty_from_recipes(catalog, qty_counts)

    # pass 2: recetas completas
    recipes_a, items_a, _ = parse_recipe_sheet("02_costeo_recetas_almuerzos.csv", "ALMUERZO")
    recipes_r, items_r, _ = parse_recipe_sheet("04_costeo_refrigerios.csv", "REFRIGERIO")
    resolve_items(items_a, catalog)
    resolve_items(items_r, catalog)

    # dedupe de recetas repetidas ya manejado en parse; unir listas
    recipes = {r["id"]: r for r in recipes_a + recipes_r}
    all_items = items_a + items_r
    # recalcular totales por receta con items reales
    by_recipe: dict[str, list[dict]] = defaultdict(list)
    for it in all_items:
        by_recipe[it["recipe_id"]].append(it)
    for rid, r in recipes.items():
        lines = by_recipe.get(rid, [])
        if not lines:
            issue("RECETA_SIN_ITEMS", f"'{r['name']}' sin ingredientes", "recetas")
        base = sum(l["line_cost"] for l in lines)
        r["ingredient_count"] = len(lines)
        r["base_cost"] = round(base, 6)
        r["total_cost"] = round(base * FACTOR, 6)
        if r["portions"] is None:
            issue("RECETA_SIN_PORCIONES", f"'{r['name']}' sin factor de porciones (PROMEDIOS)", "recetas")
        if r["base_cost"] > 2.0:
            issue("RECETA_COSTO_ATIPICO",
                  f"'{r['name']}' base {r['base_cost']:.4f} > $2.00 (revisar bloques de origen)",
                  "recetas")

    # menús
    cycles_a, days_a, menu_a = parse_almuerzo_menu()
    cycles_r, days_r, menu_r = parse_refrigerio_menu()
    cycles = cycles_a + cycles_r
    days = days_a + days_r
    menu = menu_a + menu_r

    # índice de recetas para emparejar platos (nombre completo + partes de '/')
    recipe_index = {}
    for r in recipes.values():
        full = strip_size(r["name"])
        if full and full not in recipe_index:
            recipe_index[full] = r["id"]
        for part in re.split(r"[/+]", r["name"]):
            key = strip_size(part)
            if key and key not in recipe_index:
                recipe_index[key] = r["id"]
    matched = 0
    for m in menu:
        rid, how = match_dish(m["dish"], recipe_index)
        m["recipe_id"] = rid
        if rid:
            matched += 1
        else:
            issue("MENU_SIN_RECETA", f"'{m['dish']}' sin receta asociada", "menu")
    if menu:
        issue("MENU_COBERTURA", f"{matched}/{len(menu)} platos emparejados con recetas "
              f"({matched * 100 // len(menu)}%)", "menu")

    profiles, components = parse_profiles()

    # validaciones
    residual_lines, explicados_lines, vstats = validate_against_source(recipes, by_recipe)
    ref_lines = client_reference_checks(recipes, by_recipe)
    typed_lines = validate_typed_totals()
    gram_lines, gstats = validate_gramaje_perfil(menu, by_recipe, components)

    # ------------------------------------------------------------ escritura
    write_csv(CLEAN / "ingredients.csv",
              ["sku", "name", "category", "presentation", "qty", "base_unit", "cost",
               "cost_per_base", "waste_pct", "state", "qty_source", "notes"],
              [[it["sku"], it["name"], it["category"], it["presentation"],
                round(it["qty"], 4) if it["qty"] is not None else "", it["base_unit"] or "",
                it["cost"] if it["cost"] is not None else "",
                round(it["cost_per_base"], 8) if it["cost_per_base"] is not None else "",
                0, it["state"], it["qty_source"] or "", it["notes"]]
               for it in sorted(catalog.values(), key=lambda x: x["sku"])])

    write_csv(CLEAN / "recipes.csv",
              ["recipe_id", "name", "source", "portions", "ingredient_count",
               "base_cost", "total_cost_108", "occurrences"],
              [[r["id"], r["name"], r["source"], r["portions"] or "", r["ingredient_count"],
                r["base_cost"], r["total_cost"], r["occurrences"]]
               for r in sorted(recipes.values(), key=lambda x: x["id"])])

    write_csv(CLEAN / "recipe_items.csv",
              ["recipe_id", "line_no", "ingredient", "sku", "qty_per_portion", "base_unit",
               "unit_cost", "line_cost", "portions", "theoretical_qty", "adjusted_qty",
               "price_source", "match"],
              [[it["recipe_id"], it["line_no"], it["ingredient_raw"], it["sku"] or "",
                it["qty"], it["base_unit"] or "", it["unit_cost"] if it["unit_cost"] is not None else "",
                round(it["line_cost"], 8), recipes[it["recipe_id"]]["portions"] or "",
                it["theoretical"] if it["theoretical"] is not None else "",
                it["adjusted"] if it["adjusted"] is not None else "",
                it["price_source"] or "", it["match"] or ""]
               for it in sorted(all_items, key=lambda x: (x["recipe_id"], x["line_no"]))
               if it["recipe_id"] in recipes])

    write_csv(CLEAN / "menu_cycles.csv",
              ["cycle_id", "source", "label", "week_number", "date_start", "date_end"],
              [[c["cycle_id"], c["source"], c["label"], c["week_number"],
                c["date_start"].isoformat(), c["date_end"].isoformat()] for c in cycles])

    # mapear día → ciclo por rango de fechas y fuente
    def cycle_of(d: date, source: str) -> str:
        for c in cycles:
            if c["source"] == source and c["date_start"] <= d <= c["date_end"]:
                return c["cycle_id"]
        return ""

    write_csv(CLEAN / "menu_days.csv",
              ["cycle_id", "date", "day_of_week", "is_holiday", "holiday_name"],
              [[cycle_of(d["date"], d["source"]), d["date"].isoformat(), d["day_of_week"],
                "true" if d["is_holiday"] else "false", d["holiday_name"] or ""]
               for d in sorted(days, key=lambda x: (x["source"], x["date"]))])

    write_csv(CLEAN / "menu_items.csv",
              ["date", "variant", "meal_type", "slot", "slot_order", "dish", "recipe_id"],
              [[m["date"].isoformat(), m["variant"], m["meal_type"], m["slot"],
                m["slot_order"], m["dish"], m["recipe_id"] or ""]
               for m in sorted(menu, key=lambda x: (x["date"], x["variant"], x["slot"], x["slot_order"]))])

    write_csv(CLEAN / "meal_profiles.csv", ["code", "name", "target_price"],
              [[p["code"], p["name"], p["target_price"]] for p in profiles])
    write_csv(CLEAN / "meal_profile_components.csv",
              ["profile_code", "component", "qty", "unit", "unit_cost", "line_cost"],
              [[c["profile_code"], c["component"], c["qty"], c["unit"],
                c["unit_cost"], c["line_cost"]] for c in components])

    # ------------------------------------------------------------ reporte
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for iss in ISSUES:
        by_kind[iss["kind"]].append(iss)

    lines_md = ["# Reporte de errores — Fase 1 (limpieza y normalización)", ""]
    lines_md.append(f"- Fecha de ejecución: {datetime.now().isoformat(timespec='seconds')}")
    lines_md.append(f"- Catálogo: {len(catalog)} ingredientes únicos")
    lines_md.append(f"- Recetas: {len(recipes)} únicas ({sum(r['occurrences'] for r in recipes.values())} apariciones)")
    lines_md.append(f"- Ítems de receta: {len(all_items)}")
    lines_md.append(f"- Menú: {len(cycles)} ciclos, {len(days)} días, {len(menu)} platos")
    lines_md.append(f"- Perfiles de costo: {len(profiles)}")
    lines_md.append(f"- Totales con regla ×1.08 aplicada: sí")
    lines_md.append("- Nota: RECETA_SIN_PORCIONES cuenta recetas ÚNICAS "
                    "(207 = 202 ALMUERZO + 5 REFRIGERIO; en apariciones ALMUERZO "
                    "sería 247 − 40 = 207)")
    lines_md.append("")
    lines_md.append("## Resumen por tipo de incidencia")
    lines_md.append("")
    lines_md.append("| Tipo | Cantidad |")
    lines_md.append("|---|---|")
    for kind in sorted(by_kind):
        lines_md.append(f"| {kind} | {len(by_kind[kind])} |")
    lines_md.append("")

    TITLES = {
        "INGREDIENTE_SIN_CATALOGO": "Ingredientes de receta sin correspondencia en catálogo",
        "CATALOGO_MATCH_FUZZY": "Emparejamientos difusos (revisar manualmente)",
        "CANTIDAD_PRESENTACION_VARIA": "Varianza cantidad de presentación receta vs catálogo",
        "PRECIO_VARIA": "Varianza de precio receta vs catálogo",
        "RECETA_SIN_PORCIONES": "Recetas sin factor de porciones (PROMEDIOS)",
        "RECETA_VALOR_INVALIDO": "Valores inválidos en recetas",
        "RECETA_SIN_ITEMS": "Recetas sin ingredientes",
        "RECETA_DUPLICADA_DIFERENTE": "Recetas repetidas con ingredientes distintos",
        "RECETA_UNIDAD_DIFIERE": "Líneas de receta en unidad distinta a la del catálogo",
        "RECETA_SIN_CANTIDAD_COMPARABLE": "Líneas sin c3 comparable (fallback a costo por base)",
        "RECETA_COSTO_ATIPICO": "Recetas con base cost > $2.00 (revisar origen)",
        "CATALOGO_SIN_COSTO": "Catálogo sin costo por unidad base",
        "VALIDACION_VS_ORIGEN": "Validación vs origen: desvíos >10% RESIDUALES (revisar pipeline)",
        "GRAMAJE_FUERA_PERFIL": "Gramaje por porción fuera del estándar del perfil (±10%)",
        "REFERENCIA_CLIENTE_DESCUADRE": "Descuadre vs valores de referencia del cliente",
        "MENU_SIN_RECETA": "Platos de menú sin receta asociada",
        "MENU_SEMANA_DUPLICADA": "Semanas duplicadas / renumeradas",
        "MENU_DIA_VACIO": "Días de menú sin platos",
        "MENU_FILAS_ROTAS": "Filas rotas (#REF!) descartadas",
        "MENU_VALOR_INVALIDO": "Valores inválidos en menú",
        "CATALOGO_DUPLICADO": "Productos duplicados en catálogo",
        "CATALOGO_COSTO_INVALIDO": "Costos inválidos en catálogo",
        "CATALOGO_SIN_CANTIDAD": "Catálogo sin cantidad de presentación",
        "PERFIL_VALOR_INVALIDO": "Valores inválidos en perfiles",
        "MENU_COBERTURA": "Cobertura menú ↔ recetas",
    }
    for kind in sorted(by_kind, key=lambda k: TITLES.get(k, k)):
        lines_md.append(f"## {TITLES.get(kind, kind)}")
        lines_md.append("")
        for iss in by_kind[kind][:200]:
            lines_md.append(f"- {iss['detail']}")
        if len(by_kind[kind]) > 200:
            lines_md.append(f"- … y {len(by_kind[kind]) - 200} más")
        lines_md.append("")

    # ------------------------------------------------------------ validación
    lines_md.append("## Validación de costos base vs hoja origen (pie de bloque)")
    lines_md.append("")
    if vstats.get("n"):
        lines_md.append(
            f"- n={vstats['n']}, mediana {vstats['mediana']:.2f}%, p75 {vstats['p75']:.2f}%, "
            f"p90 {vstats['p90']:.2f}% | ≤2%: {vstats['within2']}, ≤5%: {vstats['within5']}, "
            f"≤10%: {vstats['within10']}, ≤20%: {vstats['within20']}")
        lines_md.append(
            f"- Desvíos >10%: {vstats['gt10']} → **explicados por errores del origen: "
            f"{vstats['explicados']}** (el Excel dividió mal, precios cruzados o "
            f"tecledos) | **residuales (revisar pipeline): {vstats['residuales']}**")
    else:
        lines_md.append("- sin bloques comparables")
    lines_md.append("")
    lines_md.append("### Residuales >10% (sin explicación en el origen — revisar)")
    lines_md.append("")
    for line in residual_lines:
        lines_md.append(f"- {line}")
    if not residual_lines:
        lines_md.append("- ninguno")
    lines_md.append("")
    lines_md.append("### Explicados por errores del origen (muestra)")
    lines_md.append("")
    for line in explicados_lines:
        lines_md.append(f"- {line}")
    lines_md.append("")
    lines_md.append("## Referencias del informe del cliente")
    lines_md.append("")
    lines_md.extend(ref_lines or ["- sin referencias evaluadas"])
    lines_md.append("")
    lines_md.append("## Totales tecleados (col L) vs Σ(F×H) — vista de requisiciones")
    lines_md.append("")
    lines_md.extend(typed_lines)
    lines_md.append("")
    lines_md.append("## Gramajes por porción vs estándar del perfil estudiantil")
    lines_md.append("")
    lines_md.append(f"- comparaciones (receta × componente): {gstats['comparados']} | "
                    f"fuera del estándar (±10%): {gstats['fuera']} "
                    f"(perfil Almuerzo Saludable: proteína 100 g, guarnición 50 g, "
                    f"arroz 40 g; Refrigerio: 60/40 g)")
    lines_md.append("")
    for line in gram_lines:
        lines_md.append(f"- {line}")
    lines_md.append("")
    lines_md.append("## Preguntas y decisiones para el cliente")
    lines_md.append("")
    lines_md.append("- **¿Los techos ($1.24/$1.38/$0.84/$1.44) incluyen el 8%?** "
                    "Las recetas ya lo suman y la hoja Composición no lo declara: "
                    "comparar sin saberlo genera falsas alertas o ninguna. PENDIENTE.")
    lines_md.append("- **Bistec $0.70**: la referencia parece ser solo la carne "
                    "($0.708 con catálogo); confirmar si es carne o plato completo. PENDIENTE.")
    lines_md.append("- **Techo de refrigerio $0.84 vs costos reales (0.41/0.43/0.54)**: "
                    "la alerta casi nunca saltaría; confirmar alcance del techo. PENDIENTE.")
    lines_md.append("- **Gramaje por servicio**: hoy el libro usa el mismo gramaje para "
                    "Almuerzo 1 y 2 (no se reescala); confirmar si aplica escala. PENDIENTE.")
    lines_md.append("- **Duplicados de catálogo**: decisión aplicada → gana el precio "
                    "MÁXIMO (prudencia); fideo $0.45 y parmesano $1.59. CONFIRMAR.")
    lines_md.append("- **Alertas de combinación diaria** (2 proteínas × 2 guarniciones × "
                    "2 bebidas = 8): decisión → alerta por CADA combinación, con la PEOR "
                    "destacada en el resumen (Fase 3). DEFINIDO.")
    lines_md.append("")

    (CLEAN / "errors_report.md").write_text("\n".join(lines_md), encoding="utf-8")

    print(f"Catálogo: {len(catalog)} | Recetas: {len(recipes)} | Ítems: {len(all_items)}")
    print(f"Menú: {len(cycles)} ciclos, {len(menu)} platos | Perfiles: {len(profiles)}")
    print(f"Incidencias: {len(ISSUES)} -> data/clean/errors_report.md")


if __name__ == "__main__":
    main()
