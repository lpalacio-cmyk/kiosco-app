"""Cargar Venta — formulario rápido de mostrador."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import auth
import config
import queries
from db import get_session
from models import Product, Sale


st.set_page_config(page_title="Cargar Venta", layout="wide")
auth.check_password()


_LOCAL_TZ = ZoneInfo(config.TIMEZONE_DISPLAY)
_UTC = ZoneInfo("UTC")


def _hora_local(sold_at: datetime) -> str:
    return sold_at.replace(tzinfo=_UTC).astimezone(_LOCAL_TZ).strftime("%H:%M")


def _format_cantidad(q) -> str:
    s = str(q)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# Toast pendiente del rerun anterior (post-guardado).
if "pending_toast" in st.session_state:
    msg, icon = st.session_state.pop("pending_toast")
    st.toast(msg, icon=icon)

# Versión del formulario: se incrementa al guardar para forzar widgets nuevos
# y limpiar el selectbox (st.session_state.pop sobre keys de widgets es
# inestable y puede tirar StreamlitAPIException).
st.session_state.setdefault("form_version", 0)


st.subheader("Nueva Venta")


# --- Selector de producto: FUERA del form para que precio/stock se
# actualicen al elegir, antes del submit. ---
with get_session() as s:
    productos = queries.listar_productos_activos(s)

products_by_id: dict[int, Product] = {p.id: p for p in productos}

producto_id = st.selectbox(
    "Producto",
    options=list(products_by_id.keys()),
    index=None,
    format_func=lambda pid: f"{products_by_id[pid].code} — {products_by_id[pid].name}",
    placeholder="Buscá por código o nombre…",
    key=f"producto_id_{st.session_state.form_version}",
)

producto = products_by_id.get(producto_id) if producto_id is not None else None

if producto is not None:
    # NOTA: "Stock: X" es una FOTO al momento del rerun, no un lock. v0 asume una
    # sola socia operando a la vez. Multi-usuario concurrente requeriría locking
    # explícito (SELECT ... FOR UPDATE en Postgres) o reservation tokens.
    with get_session() as s:
        stock_foto = queries.stock_actual(s, producto.id)
    col_p, col_s = st.columns(2)
    col_p.markdown(f"**Precio**: {queries.formatear_pesos(producto.current_sale_price)}")
    col_s.markdown(f"**Stock**: {_format_cantidad(stock_foto)}")


# --- Formulario: cantidad, pago, nota, botón. clear_on_submit=True evita
# doble-submit por tap rápido en mobile. ---
with st.form("venta_form", clear_on_submit=True):
    cantidad = st.number_input(
        "Cantidad",
        min_value=0.001,
        value=1.0,
        step=1.0,
        format="%.3f",
    )
    metodo = st.radio(
        "Pago",
        options=list(config.PAYMENT_METHODS_DB),
        index=0,
        format_func=lambda m: config.PAYMENT_METHODS_UI[m],
        horizontal=True,
    )
    nota = ""
    if metodo == "fiado":
        nota = st.text_input("Nota (opcional)", placeholder="Juan del kiosco")
    submit = st.form_submit_button(
        "💾 Guardar Venta",
        type="primary",
        use_container_width=True,
    )


if submit:
    if producto_id is None:
        st.error("Seleccioná un producto antes de guardar.")
    else:
        cant_dec = Decimal(str(cantidad))
        with get_session() as s:
            # Re-fetch dentro de la sesión del save: garantiza que el snapshot
            # de precio y costo viene del estado MÁS RECIENTE en BD (decisión 7).
            producto_fresh = s.get(Product, producto_id)
            if producto_fresh is None:
                st.session_state["pending_toast"] = (
                    "El producto ya no existe en la base.",
                    "🚫",
                )
            else:
                stock_at_save = queries.stock_actual(s, producto_id)
                fiado_note = (
                    nota.strip()
                    if metodo == "fiado" and nota.strip()
                    else None
                )
                sale = Sale(
                    sold_at=queries.utc_naive_now(),
                    product_id=producto_fresh.id,
                    quantity=cant_dec,
                    unit_price_snapshot=producto_fresh.current_sale_price,
                    unit_cost_snapshot=producto_fresh.current_cost,
                    payment_method=metodo,
                    fiado_note=fiado_note,
                )
                s.add(sale)

                total = cant_dec * producto_fresh.current_sale_price
                if stock_at_save < cant_dec:
                    st.session_state["pending_toast"] = (
                        f"Vendida sin stock: stock {_format_cantidad(stock_at_save)}, "
                        f"vendiste {_format_cantidad(cant_dec)}. Guardada igual.",
                        "⚠️",
                    )
                else:
                    st.session_state["pending_toast"] = (
                        f"{producto_fresh.code} x {_format_cantidad(cant_dec)} = "
                        f"{queries.formatear_pesos(total)}",
                        "✅",
                    )

        # Incrementa form_version para que el selectbox arranque como widget nuevo
        # en el próximo run (opción A: post-guardado vuelve al estado inicial).
        st.session_state.form_version += 1
        st.rerun()


# --- Últimas 5 ventas de hoy (confirmación visual abajo del formulario). ---
st.subheader("Últimas ventas de hoy")
start_utc, end_utc = queries.today_range_utc()
with get_session() as s:
    ultimas = queries.ultimas_ventas(
        s, limit=5, start_utc=start_utc, end_utc=end_utc
    )

if not ultimas:
    st.info("Todavía no hay ventas hoy.")
else:
    df = pd.DataFrame(
        [
            {
                "Hora": _hora_local(v.sold_at),
                "Producto": v.product.name,
                "Cant.": _format_cantidad(v.quantity),
                "Total": queries.formatear_pesos(v.quantity * v.unit_price_snapshot),
                "Pago": config.PAYMENT_METHODS_UI[v.payment_method],
            }
            for v in ultimas
        ]
    )
    st.dataframe(df, hide_index=True, use_container_width=True)
