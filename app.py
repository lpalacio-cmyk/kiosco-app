"""Home: KPIs de hoy + atajo a Nueva Venta."""
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


st.set_page_config(page_title="Kiosco", layout="wide")
auth.check_password()


_LOCAL_TZ = ZoneInfo(config.TIMEZONE_DISPLAY)
_UTC = ZoneInfo("UTC")


def _hora_local(sold_at: datetime) -> str:
    return sold_at.replace(tzinfo=_UTC).astimezone(_LOCAL_TZ).strftime("%H:%M")


def _format_cantidad(q: Decimal) -> str:
    s = str(q)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


start_utc, end_utc = queries.today_range_utc()
with get_session() as s:
    kpis = queries.kpis_periodo(s, start_utc, end_utc)
    metodos = queries.ventas_por_metodo(s, start_utc, end_utc)
    ultimas = queries.ultimas_ventas(s, limit=5, start_utc=start_utc, end_utc=end_utc)

st.title("Kiosco — Hoy")

col1, col2, col3 = st.columns(3)
col1.metric("Ventas", queries.formatear_pesos(kpis["revenue"]))
col2.metric("Ganancia", queries.formatear_pesos(kpis["ganancia"]))
col3.metric("# Ventas", kpis["cantidad_ventas"])

col4, col5, col6 = st.columns(3)
col4.metric("Efectivo", queries.formatear_pesos(metodos["efectivo"]))
col5.metric("Transferencia", queries.formatear_pesos(metodos["transferencia"]))
col6.metric("Fiado", queries.formatear_pesos(metodos["fiado"]))

if st.button("➕ Nueva Venta", type="primary", use_container_width=True):
    st.switch_page("pages/1_Cargar_Venta.py")

st.subheader("Últimas ventas")
if not ultimas:
    st.info("No hay ventas registradas hoy todavía.")
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
