"""Migración del catálogo desde Excel a la BD.

CLI:
    python migrate_excel.py --excel <path.xlsx> [--db-url <url>] [--dry-run]

Requiere BD vacía (las 5 tablas en cero). Si encuentra datos, aborta antes
de tocar nada.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = (
    "codigo",
    "nombre",
    "categoria_original",
    "categoria_normalizada",
    "stock_inicial",
    "costo",
    "precio_venta",
)
SHEET_NAME = "Catálogo Export"
STOCK_REASON_INITIAL = "Carga inicial desde Excel"


def utc_naive_now() -> datetime:
    # BD guarda UTC naive (decisión 10). datetime.now(timezone.utc) evita el
    # utcnow() deprecado y deja claro que es UTC, no hora local.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migra el catálogo de productos desde el Excel a la BD."
    )
    p.add_argument("--excel", required=True, help="Path al archivo .xlsx.")
    p.add_argument(
        "--db-url",
        default=None,
        help="Opcional. Si se pasa, sobrescribe DB_URL para esta corrida.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Inserta dentro de la transacción y hace rollback (no persiste).",
    )
    return p.parse_args()


def abort(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_excel(path: Path) -> pd.DataFrame:
    if not path.exists():
        abort(f"Excel no encontrado: {path}")
    try:
        df = pd.read_excel(path, sheet_name=SHEET_NAME, engine="openpyxl")
    except ValueError as e:
        abort(f"No pude leer la hoja '{SHEET_NAME}': {e}")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        abort(f"Columnas faltantes en '{SHEET_NAME}': {missing}")
    return df


def detect_duplicate_codes(df: pd.DataFrame) -> list[str]:
    codes = df["codigo"].astype(str).str.strip()
    return sorted(codes[codes.duplicated(keep=False)].unique().tolist())


def assert_db_empty(session) -> None:
    from sqlalchemy import func as sa_func, select

    from models import Category, PriceHistory, Product, Sale, StockMovement

    for model in (Category, Product, PriceHistory, Sale, StockMovement):
        n = session.scalar(select(sa_func.count()).select_from(model))
        if n:
            abort(
                f"La tabla {model.__tablename__} tiene {n} filas. "
                "Esperaba BD vacía. Reseteá manualmente antes de migrar."
            )


def insert_categories(session) -> dict[str, int]:
    from config import CATEGORIES
    from models import Category

    cats = [Category(name=name, code_prefix=prefix) for name, prefix in CATEGORIES]
    session.add_all(cats)
    session.flush()
    return {c.name: c.id for c in cats}


def to_decimal(value) -> Decimal:
    # str(value) preserva la representación textual del número y evita el
    # ruido binario de Decimal(float).
    return Decimal(str(value))


def build_products(
    df: pd.DataFrame,
    category_id_by_name: dict[str, int],
) -> tuple[list, list[tuple[object, Decimal]], dict]:
    from models import Product

    products: list = []
    pending: list[tuple[object, Decimal]] = []
    stats: dict = {"categoria_diff": 0, "negativos": []}

    for excel_row_index, row in df.iterrows():
        excel_row = int(excel_row_index) + 2  # +2: encabezado + 0-index
        code = str(row["codigo"]).strip()
        name = str(row["nombre"]).strip()
        cat_norm = str(row["categoria_normalizada"]).strip()
        cat_orig = str(row["categoria_original"]).strip()

        if cat_norm != cat_orig:
            stats["categoria_diff"] += 1

        if cat_norm not in category_id_by_name:
            abort(
                f"Fila {excel_row} (codigo={code!r}): categoria_normalizada "
                f"{cat_norm!r} no está en las 12 canónicas."
            )

        stock_inicial = to_decimal(row["stock_inicial"])
        if stock_inicial < 0:
            print(
                f"WARNING fila {excel_row} (codigo={code!r}): "
                f"stock_inicial={stock_inicial} negativo. Lo inserto igual.",
                file=sys.stderr,
            )
            stats["negativos"].append((code, stock_inicial))

        product = Product(
            code=code,
            name=name,
            category_id=category_id_by_name[cat_norm],
            is_weighted=False,
            current_cost=to_decimal(row["costo"]),
            current_sale_price=to_decimal(row["precio_venta"]),
            active=True,
        )
        products.append(product)
        pending.append((product, stock_inicial))

    return products, pending, stats


def build_stock_movements(
    pending: list[tuple[object, Decimal]],
    occurred_at: datetime,
) -> list:
    from models import StockMovement

    return [
        StockMovement(
            product_id=p.id,
            quantity_delta=qty,
            reason=STOCK_REASON_INITIAL,
            occurred_at=occurred_at,
            notes=None,
        )
        for p, qty in pending
    ]


def print_summary(
    df: pd.DataFrame,
    n_categories: int,
    stats: dict,
    dry_run: bool,
) -> None:
    print()
    print("=== RESUMEN ===")
    print(f"Productos en Excel:       {len(df)}")
    print(f"Categorías insertadas:    {n_categories}")
    print(
        "Filas con categoria_original != categoria_normalizada: "
        f"{stats['categoria_diff']}"
    )
    print(f"Productos con stock_inicial negativo: {len(stats['negativos'])}")
    for code, qty in stats["negativos"]:
        print(f"  - {code}: {qty}")
    print()
    print("Conteo de productos por categoría:")
    counts = (
        df.groupby("categoria_normalizada").size().sort_values(ascending=False)
    )
    for cat, n in counts.items():
        print(f"  {cat:<14} {n}")
    print()
    print(f"Suma total stock_inicial: {df['stock_inicial'].sum()}")
    print()
    if dry_run:
        print("DRY-RUN: rollback ejecutado. Nada quedó persistido.")
    else:
        print("Migración completada.")


def main() -> None:
    args = parse_args()
    if args.db_url:
        os.environ["DB_URL"] = args.db_url

    # Imports después de setear DB_URL para que db.py lo resuelva correctamente.
    from db import SessionLocal, get_engine, init_db

    excel_path = Path(args.excel)
    df = load_excel(excel_path)

    dups = detect_duplicate_codes(df)
    if dups:
        abort(f"Códigos duplicados en columna 'codigo' del Excel: {dups}")

    init_db()
    session = SessionLocal(bind=get_engine())
    try:
        assert_db_empty(session)
        print(f"Leyendo {len(df)} filas de '{SHEET_NAME}' en {excel_path}")

        category_id_by_name = insert_categories(session)
        print(f"Insertadas {len(category_id_by_name)} categorías (flush).")

        products, pending, stats = build_products(df, category_id_by_name)
        session.add_all(products)
        session.flush()
        print(f"Insertados {len(products)} productos (flush).")

        movements = build_stock_movements(pending, utc_naive_now())
        session.add_all(movements)
        session.flush()
        print(f"Insertados {len(movements)} stock_movements iniciales (flush).")

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        print_summary(df, len(category_id_by_name), stats, args.dry_run)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
