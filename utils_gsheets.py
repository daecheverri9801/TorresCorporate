# utils_gsheets.py --------------------------------------------------
import os, json, gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]

   # ---------- helpers internos --------------------------------------
def _get_raw_creds():
       return (os.getenv("GSHEETS_CREDS_JSON") or
               st.secrets.get("gservice_key", ""))

def _get_sheet_url(url_override=None):
       if url_override:
           return url_override
       return (os.getenv("GSHEETS_URL") or
               st.secrets.get("gsheet_url", ""))

   # ---------- cliente gspread --------------------------------------
def _get_client():
       raw_json = _get_raw_creds()
       if not raw_json:
           raise RuntimeError("Faltan credenciales de service-account")
       info  = json.loads(raw_json)
       creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
       return gspread.authorize(creds)

   # ---------- función pública --------------------------------------
def update_master(df: pd.DataFrame, sheet_url: str | None = None):
       """
       Inserta todas las filas del DataFrame (columnas Tracking Number y
       full_address) al final de la Google Sheet indicada.
       Salta silenciosamente si no hay URL ni credenciales.
       """
       sheet_url = _get_sheet_url(sheet_url)
       if not sheet_url:
           return  # no hay configuración ⇒ no hacemos nada

       filas = (df[["Tracking Number", "full_address"]]
                .astype(str).values.tolist())

       # opcional • evitar duplicados locales
    #    filas = list({tuple(r) for r in filas})

       client = _get_client()
       sh     = client.open_by_url(sheet_url)
       wks    = sh.sheet1
       wks.append_rows(filas, value_input_option="RAW")