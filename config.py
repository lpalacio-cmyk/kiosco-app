"""Constantes del dominio: split socias, métodos de pago, categorías, timezone."""
from __future__ import annotations

from decimal import Decimal

# Split de ganancias entre las socias (decisión 5 de CLAUDE.md).
SPLIT_RITA: Decimal = Decimal("0.70")
SPLIT_GABY: Decimal = Decimal("0.30")
assert SPLIT_RITA + SPLIT_GABY == Decimal("1"), "El split de socias debe sumar 1"


# Métodos de pago: (valor_db, label_ui). Fuente única; derivados abajo.
# El valor_db debe coincidir EXACTO con el CheckConstraint de models.Sale.
PAYMENT_METHODS: tuple[tuple[str, str], ...] = (
    ("efectivo", "Efectivo"),
    ("transferencia", "Transferencia"),
    ("fiado", "Fiado"),
)
PAYMENT_METHODS_DB: tuple[str, ...] = tuple(db for db, _ in PAYMENT_METHODS)
PAYMENT_METHODS_UI: dict[str, str] = dict(PAYMENT_METHODS)


# Categorías canónicas (12) y sus prefijos de código (sección "Categorías" de CLAUDE.md).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Almacen", "A"),
    ("Bebidas", "B"),
    ("Farmacia", "F"),
    ("Golosinas", "G"),
    ("Helados", "H"),
    ("Libreria", "LI"),
    ("Limpieza", "L"),
    ("Otros", "O"),
    ("Perfumeria", "P"),
    ("Repuesto", "R"),
    ("Snack", "S"),
    ("Verduras", "V"),
)
CATEGORY_NAMES: tuple[str, ...] = tuple(name for name, _ in CATEGORIES)
CATEGORY_PREFIXES: dict[str, str] = dict(CATEGORIES)
# Ordenado por longitud de prefijo descendente: 'LI' antes que 'L' al parsear códigos.
CATEGORY_PREFIXES_BY_LENGTH: tuple[tuple[str, str], ...] = tuple(
    sorted(CATEGORIES, key=lambda c: -len(c[1]))
)


# Timezone para mostrar fechas en la UI. La BD guarda UTC (decisión 10).
# String literal: instanciar ZoneInfo(TIMEZONE_DISPLAY) en cada módulo de UI.
TIMEZONE_DISPLAY: str = "America/Argentina/Catamarca"
