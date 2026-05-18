"""Productos — catálogo: ver, buscar, editar, agregar."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select

import auth
import config
import queries
from db import get_session
from models import Category, PriceHistory, Product, StockMovement


st.set_page_config(page_title="Productos", layout="wide")
auth.check_password()


EDITABLE_COLS = ("name", "current_cost", "current_sale_price", "is_weighted", "active")


def _format_cantidad(q) -> str:
    s = str(q)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# Toast pendiente del rerun anterior.
if "pending_toast" in st.session_state:
    msg, icon = st.session_state.pop("pending_toast")
    st.toast(msg, icon=icon)

# Versión del editor: se incrementa al guardar para limpiar el estado del
# st.data_editor en el próximo rerun y evitar que edits viejos se re-apliquen
# sobre el df recién leído de BD.
st.session_state.setdefault("editor_version", 0)


st.subheader("Productos")


# --- Filtros ---
col_q, col_c = st.columns(2)
search = col_q.text_input("Buscar", placeholder="Código o nombre…")
categoria_filter = col_c.selectbox(
    "Categoría",
    options=["Todas"] + list(config.CATEGORY_NAMES),
    index=0,
)
solo_activos = st.checkbox("Solo activos", value=True)


# --- Cargar productos + stock bulk ---
with get_session() as s:
    productos = queries.listar_productos(s, solo_activos=solo_activos)
    product_ids = [p.id for p in productos]
    stocks = queries.stock_actual_bulk(s, product_ids=product_ids)

rows = [
    {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "category": p.category.name,
        "current_cost": float(p.current_cost),
        "current_sale_price": float(p.current_sale_price),
        "is_weighted": p.is_weighted,
        "active": p.active,
        "stock_actual": float(stocks.get(p.id, Decimal(0))),
    }
    for p in productos
]
df_full = pd.DataFrame(rows)


# --- Aplicar filtros en pandas ---
df_filtered = df_full.copy()
if search.strip():
    pat = search.strip().lower()
    mask = df_filtered["code"].str.lower().str.contains(pat, regex=False) | \
           df_filtered["name"].str.lower().str.contains(pat, regex=False)
    df_filtered = df_filtered[mask].reset_index(drop=True)
if categoria_filter != "Todas":
    df_filtered = df_filtered[df_filtered["category"] == categoria_filter].reset_index(drop=True)


# Slot para info-bar + botón Guardar (se renderiza ABAJO del editor pero
# queda visible ARRIBA gracias a st.empty()).
status_slot = st.empty()


# --- Tabla editable ---
edited_df = st.data_editor(
    df_filtered,
    column_config={
        "id": None,
        "code": st.column_config.TextColumn("Código", disabled=True),
        "name": st.column_config.TextColumn("Nombre"),
        "category": st.column_config.TextColumn("Categoría", disabled=True),
        "current_cost": st.column_config.NumberColumn(
            "Costo", min_value=0.0, format="%.2f"
        ),
        "current_sale_price": st.column_config.NumberColumn(
            "Precio", min_value=0.0, format="%.2f"
        ),
        "is_weighted": st.column_config.CheckboxColumn("Por peso"),
        "active": st.column_config.CheckboxColumn("Activo"),
        "stock_actual": st.column_config.NumberColumn(
            "Stock", disabled=True, format="%g"
        ),
    },
    hide_index=True,
    width="stretch",
    height=450,
    num_rows="fixed",
    key=f"productos_editor_{st.session_state.editor_version}",
)


def _compute_changes(original: pd.DataFrame, edited: pd.DataFrame) -> list[dict]:
    changes = []
    for i in range(len(original)):
        orig = original.iloc[i]
        ed = edited.iloc[i]
        diff: dict = {}
        for col in EDITABLE_COLS:
            ov, ev = orig[col], ed[col]
            if isinstance(ov, float):
                if abs(ov - ev) > 1e-9:
                    diff[col] = ev
            elif ov != ev:
                diff[col] = ev
        if diff:
            changes.append({"id": int(orig["id"]), "code": orig["code"], "diff": diff})
    return changes


changes = _compute_changes(df_filtered, edited_df)


# LIMITACIÓN CONOCIDA: este indicador alerta visualmente pero no previene
# la pérdida de cambios si el usuario navega a otra página de la app antes
# de tappear "Guardar cambios". Streamlit no expone un hook before-navigate.
# Aceptado para v0.
with status_slot.container():
    if changes:
        col_msg, col_btn = st.columns([2, 1])
        col_msg.markdown(f":red[**⚠️ {len(changes)} cambio(s) sin guardar**]")
        save = col_btn.button(
            f"💾 Guardar {len(changes)} cambio(s)",
            type="primary",
            width="stretch",
            key="save_changes_btn",
        )
    else:
        st.caption(f"{len(df_filtered)} producto(s) — sin cambios")
        save = False


# --- Persistencia de cambios ---
if save and changes:
    # Defensa server-side: rechazar negativos antes de tocar BD (NumberColumn
    # con min_value=0 es validación client-side y no garantiza nada server-side).
    invalid = []
    for ch in changes:
        d = ch["diff"]
        if "current_cost" in d and d["current_cost"] < 0:
            invalid.append((ch["code"], "current_cost", d["current_cost"]))
        if "current_sale_price" in d and d["current_sale_price"] < 0:
            invalid.append((ch["code"], "current_sale_price", d["current_sale_price"]))

    if invalid:
        detalle = ", ".join(f"{c} ({col}={v})" for c, col, v in invalid)
        st.session_state["pending_toast"] = (
            f"Cambios rechazados (valores negativos): {detalle}",
            "🚫",
        )
        st.rerun()

    try:
        now = queries.utc_naive_now()
        with get_session() as s:
            for ch in changes:
                p = s.get(Product, ch["id"])
                if p is None:
                    raise RuntimeError(f"Producto id={ch['id']} ya no existe.")
                d = ch["diff"]
                cost_changed = "current_cost" in d
                price_changed = "current_sale_price" in d
                if "name" in d:
                    p.name = d["name"]
                if cost_changed:
                    p.current_cost = Decimal(str(d["current_cost"]))
                if price_changed:
                    p.current_sale_price = Decimal(str(d["current_sale_price"]))
                if "is_weighted" in d:
                    p.is_weighted = bool(d["is_weighted"])
                if "active" in d:
                    p.active = bool(d["active"])
                if cost_changed or price_changed:
                    s.add(
                        PriceHistory(
                            product_id=p.id,
                            cost=p.current_cost,
                            sale_price=p.current_sale_price,
                            effective_from=now,
                        )
                    )
        st.session_state["pending_toast"] = (
            f"{len(changes)} producto(s) actualizado(s).",
            "✅",
        )
    except Exception as e:
        st.session_state["pending_toast"] = (
            f"Error al guardar: {type(e).__name__}: {e}",
            "🚫",
        )

    st.session_state.editor_version += 1
    st.rerun()


# --- Form: nuevo producto ---
with st.expander("➕ Nuevo producto", expanded=False):
    with st.form("nuevo_producto", clear_on_submit=True):
        np_code = st.text_input("Código")
        np_name = st.text_input("Nombre")
        np_category_name = st.selectbox(
            "Categoría",
            options=list(config.CATEGORY_NAMES),
            index=None,
            placeholder="Elegí una categoría…",
        )
        np_is_weighted = st.checkbox("Por peso (kg)", value=False)
        np_cost = st.number_input("Costo", min_value=0.0, value=0.0, step=1.0, format="%.2f")
        np_sale = st.number_input("Precio de venta", min_value=0.0, value=0.0, step=1.0, format="%.2f")
        np_stock = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=1.0, format="%.3f")
        create = st.form_submit_button("Crear", type="primary", width="stretch")

if create:
    np_code = (np_code or "").strip()
    np_name = (np_name or "").strip()
    err = None
    if not np_code:
        err = "El código no puede estar vacío."
    elif not np_name:
        err = "El nombre no puede estar vacío."
    elif np_category_name is None:
        err = "Elegí una categoría."
    elif np_cost < 0 or np_sale < 0:
        err = "Costo y precio no pueden ser negativos."

    if err:
        st.session_state["pending_toast"] = (err, "🚫")
        st.rerun()

    try:
        with get_session() as s:
            if queries.get_product_by_code(s, np_code) is not None:
                raise ValueError(f"Ya existe un producto con código {np_code!r}.")
            cat = s.scalar(select(Category).where(Category.name == np_category_name))
            if cat is None:
                raise ValueError(f"Categoría {np_category_name!r} no encontrada.")

            new_p = Product(
                code=np_code,
                name=np_name,
                category_id=cat.id,
                is_weighted=np_is_weighted,
                current_cost=Decimal(str(np_cost)),
                current_sale_price=Decimal(str(np_sale)),
                active=True,
            )
            s.add(new_p)
            s.flush()

            if np_stock > 0:
                s.add(
                    StockMovement(
                        product_id=new_p.id,
                        quantity_delta=Decimal(str(np_stock)),
                        reason="Stock inicial al crear producto",
                        occurred_at=queries.utc_naive_now(),
                    )
                )
        st.session_state["pending_toast"] = (f"Producto {np_code} creado.", "✅")
    except Exception as e:
        st.session_state["pending_toast"] = (
            f"Error al crear: {type(e).__name__}: {e}",
            "🚫",
        )

    st.rerun()
