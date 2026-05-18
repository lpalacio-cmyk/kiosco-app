"""Autenticación por contraseña compartida (decisión 4 de CLAUDE.md)."""
from __future__ import annotations

import hmac

import streamlit as st


def _get_app_password() -> str:
    try:
        password = st.secrets["APP_PASSWORD"]
    except (KeyError, FileNotFoundError):
        st.error(
            "APP_PASSWORD no configurada en .streamlit/secrets.toml. "
            "Copiá secrets.toml.example y completá el valor."
        )
        st.stop()
    if not password:
        st.error("APP_PASSWORD está vacía en secrets.toml.")
        st.stop()
    return password


def check_password() -> None:
    """Bloquea la página si no hay sesión autenticada.

    Llamar como primera línea de app.py y de cada page. Si el usuario
    no se autenticó, renderiza un formulario y corta con st.stop().
    """
    if st.session_state.get("authenticated") is True:
        return

    app_password = _get_app_password()

    with st.form("login_form", clear_on_submit=True):
        st.subheader("Acceso")
        entered = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        if hmac.compare_digest(entered, app_password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")

    st.stop()
