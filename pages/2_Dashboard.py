"""Dashboard — KPIs, serie diaria y top productos por rango de fechas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import config
import queries
from db import get_session


st.set_page_config(page_title="Dashboard", layout="wide")
auth.check_password()


def _format_cantidad(q) -> str:
    s = str(q)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


st.subheader("Dashboard")


# --- Selector de rango ---
today_local = datetime.now(ZoneInfo(config.TIMEZONE_DISPLAY)).date()
rango = st.date_input(
    "Rango de fechas",
    value=(today_local, today_local),
    format="DD/MM/YYYY",
)
if not isinstance(rango, tuple) or len(rango) != 2:
    st.info("Seleccioná un rango completo (fecha inicio y fecha fin).")
    st.stop()

start_local_date, end_local_date = rango
start_utc, end_utc = queries.range_utc_from_local_dates(
    start_local_date, end_local_date
)


with get_session() as s:
    kpis = queries.kpis_periodo(s, start_utc, end_utc)
    metodos = queries.ventas_por_metodo(s, start_utc, end_utc)
    df_serie = queries.serie_diaria(s, start_utc, end_utc)
    df_top = queries.top_productos(s, start_utc, end_utc, limit=10)

split = queries.ganancia_por_socia(kpis["ganancia"])


# --- KPIs principales ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Ventas",     queries.formatear_pesos(kpis["revenue"]))
col2.metric("Ganancia",   queries.formatear_pesos(kpis["ganancia"]))
col3.metric("Rita (70%)", queries.formatear_pesos(split["Rita"]))
col4.metric("Gaby (30%)", queries.formatear_pesos(split["Gaby"]))


# --- Ventas por método ---
col5, col6, col7 = st.columns(3)
col5.metric("Efectivo",      queries.formatear_pesos(metodos["efectivo"]))
col6.metric("Transferencia", queries.formatear_pesos(metodos["transferencia"]))
col7.metric("Fiado",         queries.formatear_pesos(metodos["fiado"]))


# --- Caso "sin ventas" ---
if kpis["cantidad_ventas"] == 0:
    st.info("No hay ventas en este período.")
    st.stop()


# --- Gráfico de línea: solo si el rango es de 2 o más días ---
# 1 punto solo no aporta información visual; saltear el chart y mostrar
# solo los KPIs y la tabla en ese caso.
if (end_local_date - start_local_date).days >= 1:
    st.subheader("Ventas y ganancia por día")

    # Solo para Plotly (no acepta Decimal). NUNCA usar este patrón para
    # totales que persistan o se muestren al usuario: Decimal→float puede
    # introducir imprecisión binaria.
    df_long = df_serie.melt(
        id_vars="fecha",
        value_vars=["revenue", "ganancia"],
        var_name="serie",
        value_name="monto",
    )
    df_long["monto_float"] = df_long["monto"].astype(float)
    df_long["monto_str"] = df_long["monto"].apply(queries.formatear_pesos)
    df_long["serie"] = df_long["serie"].map(
        {"revenue": "Ventas", "ganancia": "Ganancia"}
    )

    fig = px.line(
        df_long,
        x="fecha",
        y="monto_float",
        color="serie",
        labels={"fecha": "Fecha", "monto_float": "$", "serie": ""},
        color_discrete_map={"Ventas": "#90A4AE", "Ganancia": "#2E7D32"},
        custom_data=["monto_str"],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{x|%d/%m/%Y}</b><br>"
            "%{customdata[0]}"
            "<extra>%{fullData.name}</extra>"
        ),
    )
    fig.update_layout(legend_title_text="", margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")


# --- Top 10 productos ---
st.subheader("Top 10 productos")
if df_top.empty:
    st.info("Sin datos de productos en el período.")
else:
    display = df_top.copy()
    display["unidades"] = display["unidades"].apply(_format_cantidad)
    display["revenue"] = display["revenue"].apply(queries.formatear_pesos)
    display["ganancia"] = display["ganancia"].apply(queries.formatear_pesos)
    display = display.rename(
        columns={
            "code": "Código",
            "name": "Producto",
            "unidades": "Unidades",
            "revenue": "Ventas",
            "ganancia": "Ganancia",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")
