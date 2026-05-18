"""Queries de agregación read-only sobre el modelo."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from config import (
    PAYMENT_METHODS_DB,
    SPLIT_GABY,
    SPLIT_RITA,
    TIMEZONE_DISPLAY,
)
from models import Product, Sale, StockMovement


_UTC = ZoneInfo("UTC")


def _to_local_date(utc_naive: datetime) -> date:
    """Convierte un datetime UTC naive al date local de Catamarca."""
    return utc_naive.replace(tzinfo=_UTC).astimezone(ZoneInfo(TIMEZONE_DISPLAY)).date()


def today_range_utc() -> tuple[datetime, datetime]:
    """Rango [start, end) en UTC naive que corresponde a 'hoy' local Catamarca."""
    tz = ZoneInfo(TIMEZONE_DISPLAY)
    today_local = datetime.now(tz).date()
    start_local = datetime.combine(today_local, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(_UTC).replace(tzinfo=None),
        end_local.astimezone(_UTC).replace(tzinfo=None),
    )


def formatear_pesos(valor: Decimal) -> str:
    """Formato argentino: $1.234,56 (punto miles, coma decimales)."""
    crudo = f"{valor:,.2f}"
    swapped = crudo.replace(",", "·").replace(".", ",").replace("·", ".")
    return f"${swapped}"


def get_product_by_code(session: Session, code: str) -> Product | None:
    """Resuelve un código exacto a un Product, o None si no existe."""
    return session.scalar(select(Product).where(Product.code == code))


def buscar_productos(
    session: Session,
    term: str = "",
    categoria_id: int | None = None,
    solo_activos: bool = True,
) -> list[Product]:
    """Búsqueda por code/name + filtro categoría; vacío si term y categoria_id son ambos None."""
    term = term.strip()
    if not term and categoria_id is None:
        return []

    stmt = select(Product)
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(Product.code.ilike(pattern) | Product.name.ilike(pattern))
    if categoria_id is not None:
        stmt = stmt.where(Product.category_id == categoria_id)
    if solo_activos:
        stmt = stmt.where(Product.active.is_(True))
    stmt = stmt.order_by(Product.name)
    return list(session.scalars(stmt))


def stock_actual(session: Session, product_id: int) -> Decimal:
    """Stock = SUM(stock_movements.quantity_delta) - SUM(sales.quantity)."""
    movs = session.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
            StockMovement.product_id == product_id
        )
    )
    ventas = session.scalar(
        select(func.coalesce(func.sum(Sale.quantity), 0)).where(
            Sale.product_id == product_id
        )
    )
    return Decimal(movs) - Decimal(ventas)


def stock_actual_bulk(
    session: Session,
    product_ids: list[int] | None = None,
) -> dict[int, Decimal]:
    """Stock por producto; si product_ids es None solo devuelve productos con actividad."""
    mov_stmt = select(
        StockMovement.product_id,
        func.coalesce(func.sum(StockMovement.quantity_delta), 0),
    ).group_by(StockMovement.product_id)
    if product_ids is not None:
        mov_stmt = mov_stmt.where(StockMovement.product_id.in_(product_ids))
    movs = dict(session.execute(mov_stmt).all())

    ventas_stmt = select(
        Sale.product_id,
        func.coalesce(func.sum(Sale.quantity), 0),
    ).group_by(Sale.product_id)
    if product_ids is not None:
        ventas_stmt = ventas_stmt.where(Sale.product_id.in_(product_ids))
    ventas = dict(session.execute(ventas_stmt).all())

    if product_ids is not None:
        ids = set(product_ids)
    else:
        ids = set(movs.keys()) | set(ventas.keys())

    return {
        pid: Decimal(movs.get(pid, 0)) - Decimal(ventas.get(pid, 0))
        for pid in ids
    }


def kpis_periodo(
    session: Session,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Decimal | int]:
    """Revenue, ganancia y cantidad_ventas en [start_utc, end_utc); ceros si no hay datos."""
    row = session.execute(
        select(
            func.coalesce(
                func.sum(Sale.quantity * Sale.unit_price_snapshot), 0
            ).label("revenue"),
            func.coalesce(
                func.sum(
                    Sale.quantity
                    * (Sale.unit_price_snapshot - Sale.unit_cost_snapshot)
                ),
                0,
            ).label("ganancia"),
            func.count().label("cantidad_ventas"),
        ).where(Sale.sold_at >= start_utc, Sale.sold_at < end_utc)
    ).one()
    return {
        "revenue": Decimal(row.revenue),
        "ganancia": Decimal(row.ganancia),
        "cantidad_ventas": int(row.cantidad_ventas),
    }


def ventas_por_metodo(
    session: Session,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Decimal]:
    """Revenue por método de pago; siempre devuelve las 3 keys con 0 default."""
    rows = session.execute(
        select(
            Sale.payment_method,
            func.coalesce(func.sum(Sale.quantity * Sale.unit_price_snapshot), 0),
        )
        .where(Sale.sold_at >= start_utc, Sale.sold_at < end_utc)
        .group_by(Sale.payment_method)
    ).all()
    found = {method: Decimal(total) for method, total in rows}
    return {m: found.get(m, Decimal("0")) for m in PAYMENT_METHODS_DB}


def ultimas_ventas(session: Session, limit: int = 5) -> list[Sale]:
    """Últimas N ventas con product eager-loaded."""
    return list(
        session.scalars(
            select(Sale)
            .options(selectinload(Sale.product))
            .order_by(Sale.sold_at.desc())
            .limit(limit)
        )
    )


def serie_diaria(
    session: Session,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    """Revenue y ganancia por día local Catamarca; backfill con ceros."""
    rows = session.execute(
        select(
            Sale.sold_at,
            Sale.quantity,
            Sale.unit_price_snapshot,
            Sale.unit_cost_snapshot,
        ).where(Sale.sold_at >= start_utc, Sale.sold_at < end_utc)
    ).all()

    # Backfill sobre fechas LOCALES (Catamarca), no UTC.
    start_local = _to_local_date(start_utc)
    end_local = _to_local_date(end_utc - timedelta(microseconds=1))
    all_days = [d.date() for d in pd.date_range(start=start_local, end=end_local, freq="D")]

    if not rows:
        return pd.DataFrame(
            {
                "fecha": all_days,
                "revenue": [Decimal("0")] * len(all_days),
                "ganancia": [Decimal("0")] * len(all_days),
            }
        )

    df = pd.DataFrame(rows, columns=["sold_at", "quantity", "price", "cost"])
    df["fecha"] = (
        pd.to_datetime(df["sold_at"])
        .dt.tz_localize("UTC")
        .dt.tz_convert(TIMEZONE_DISPLAY)
        .dt.date
    )
    df["revenue"] = df["quantity"] * df["price"]
    df["ganancia"] = df["quantity"] * (df["price"] - df["cost"])
    agg = df.groupby("fecha")[["revenue", "ganancia"]].sum()
    full = agg.reindex(all_days, fill_value=Decimal("0"))
    full.index.name = "fecha"
    return full.reset_index()


def top_productos(
    session: Session,
    start_utc: datetime,
    end_utc: datetime,
    limit: int = 10,
) -> pd.DataFrame:
    """Top N productos por revenue; tiebreak: unidades DESC."""
    revenue_expr = func.sum(Sale.quantity * Sale.unit_price_snapshot)
    unidades_expr = func.sum(Sale.quantity)
    ganancia_expr = func.sum(
        Sale.quantity * (Sale.unit_price_snapshot - Sale.unit_cost_snapshot)
    )
    rows = session.execute(
        select(
            Product.code,
            Product.name,
            unidades_expr.label("unidades"),
            revenue_expr.label("revenue"),
            ganancia_expr.label("ganancia"),
        )
        .join(Sale, Sale.product_id == Product.id)
        .where(Sale.sold_at >= start_utc, Sale.sold_at < end_utc)
        .group_by(Product.id, Product.code, Product.name)
        .order_by(revenue_expr.desc(), unidades_expr.desc())
        .limit(limit)
    ).all()
    columns = ["code", "name", "unidades", "revenue", "ganancia"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def ganancia_por_socia(ganancia: Decimal) -> dict[str, Decimal]:
    """Split 70/30 según config; quantize a 2 decimales."""
    q = Decimal("0.01")
    return {
        "Rita": (ganancia * SPLIT_RITA).quantize(q),
        "Gaby": (ganancia * SPLIT_GABY).quantize(q),
    }
