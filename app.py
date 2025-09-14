# ================================================================
# Streamlit App  :  Geocodificar Direcciones + Zona/Subzona
# ================================================================
import os, zipfile, shutil, time, warnings, io
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import googlemaps
from tqdm import tqdm
import streamlit as st
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------- Configuración Streamlit ------------------
st.set_page_config(page_title="Geocodificar Direcciones Torres Corporate",
                   page_icon="🌎",
                   layout="wide")

st.title("🌎 Geocodificar direcciones y asignar zonas")
st.write("""
1. **Sube** tu Excel con las columnas de dirección  
2. **Procesa** (se usará la caché para no gastar cuota)  
3. **Descarga** el Excel 
""")

# ------------------- Parámetros y archivos fijos -----------------
DATA_DIR      = "data"
CACHE_FILE    = "cache_geocoding.csv"
KMZ_FILES     = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                 if f.lower().endswith(".kmz")]

# ------------------ Selección / introducción API KEY -------------
api_key = st.text_input(
    "🔑 Google Maps Geocoding API key",
    value=os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyCkZG7fbor17mhs3NLjaThcChO-Pav67gA"),
    type="password",
    help="Se puede dejar vacío si la variable de entorno GOOGLE_MAPS_API_KEY ya está definida"
)
PROCESS_BTN_LABEL = "🚀 Procesar direcciones"

st.divider()

# -------------------------- Cargar caché -------------------------
def load_cache():
    if os.path.exists(CACHE_FILE) and os.path.getsize(CACHE_FILE) > 0:
        return pd.read_csv(CACHE_FILE)
    return pd.DataFrame(columns=["full_address", "latitude",
                                 "longitude", "geocode_status"])

cache_df = load_cache()

# ------------------------- Funciones utilitarias -----------------
def build_address(row) -> str:
    parts = [
        str(row.get("Buyer Address1", "")).strip(),
        str(row.get("Buyer Address1 Number", "")).strip(),
        str(row.get("Buyer City", "")).strip(),
        "Colombia",
    ]
    return ", ".join([p for p in parts if p and p.lower() != "nan"])


@st.cache_resource(show_spinner=False)
def load_polygons():
    """Carga y concatena los KMZ (solo la 1ª vez)."""
    def kmz_to_gdf(kmz_path: str) -> gpd.GeoDataFrame:
        zona = os.path.basename(kmz_path).replace(".kmz", "")
        tmp = kmz_path.replace(".kmz", "_tmp")
        with zipfile.ZipFile(kmz_path) as zf:
            zf.extractall(tmp)
        kml = next((f for f in os.listdir(tmp) if f.endswith(".kml")), None)
        if not kml:
            shutil.rmtree(tmp);  return gpd.GeoDataFrame()
        gdf = gpd.read_file(os.path.join(tmp, kml), driver="KML")
        gdf["zona"] = zona
        gdf["subzona"] = (
            gdf["Name"].fillna(gdf.get("Description")).fillna("Sin_nombre")
            if "Name" in gdf.columns else
            gdf.get("Description", pd.Series(["Sin_nombre"]*len(gdf)))
        )
        shutil.rmtree(tmp)
        return gdf

    gdfs = [kmz_to_gdf(f) for f in KMZ_FILES]
    gdf_pol = pd.concat(gdfs, ignore_index=True).to_crs(4326)
    return gdf_pol


def geocode_enhanced(gmaps_cli, address: str, max_retries: int = 3):
    for _ in range(max_retries):
        try:
            res = gmaps_cli.geocode(address, region="co", language="es")
            if res:
                loc = res[0]["geometry"]["location"]
                return loc["lat"], loc["lng"], "completa"
        except Exception:
            time.sleep(0.8)
    # fallback
    try:
        city = address.split(",")[-2] + ", Colombia"
        res = gmaps_cli.geocode(city, region="co", language="es")
        if res:
            loc = res[0]["geometry"]["location"]
            return loc["lat"], loc["lng"], "ciudad"
    except Exception:
        pass
    return None, None, "fallida"


def geocode_with_cache(gmaps_cli, address: str):
    global cache_df
    cached = cache_df.loc[cache_df.full_address == address]
    if not cached.empty:
        row = cached.iloc[0]
        return row.latitude, row.longitude, row.geocode_status, True
    lat, lon, status = geocode_enhanced(gmaps_cli, address)
    cache_df.loc[len(cache_df)] = [address, lat, lon, status]
    return lat, lon, status, False


def process_file(uploaded_file, api_key):
    df = pd.read_excel(uploaded_file).copy()
    df.reset_index(drop=True, inplace=True)
    df["full_address"] = df.apply(build_address, axis=1)

    gmaps_cli = googlemaps.Client(api_key)

    lat, lon, status = [], [], []
    api_calls, cache_hits = 0, 0

    progress = st.progress(0)
    for i, addr in enumerate(df.full_address):
        la, lo, stt, from_cache = geocode_with_cache(gmaps_cli, addr)
        lat.append(la); lon.append(lo); status.append(stt)
        if from_cache: cache_hits += 1
        else:          api_calls  += 1
        progress.progress((i+1)/len(df))
    progress.empty()

    df["latitude"] = lat
    df["longitude"] = lon
    df["geocode_status"] = status
    cache_df.to_csv(CACHE_FILE, index=False)

    # -------------- Spatial join -----------------
    gdf_pol = load_polygons()

    df_valid = df[df.latitude.notna() & df.longitude.notna()].copy()
    gdf_pts  = gpd.GeoDataFrame(
        df_valid.reset_index().rename(columns={"index":"idx_orig"}),
        geometry=[Point(xy) for xy in zip(df_valid.longitude, df_valid.latitude)],
        crs=4326)

    gdf_join = gpd.sjoin(
        gdf_pts, gdf_pol[["zona", "subzona", "geometry"]],
        how="left", predicate="within"
    ).drop_duplicates(subset="idx_orig").set_index("idx_orig")

    # buffer 100 m para faltantes
    faltan = gdf_join.zona.isna()
    if faltan.any():
        pts_proj = gdf_pts.to_crs(3116)
        pol_proj = gdf_pol.to_crs(3116)
        pts_proj["geometry"] = pts_proj.buffer(100)
        join_buff = gpd.sjoin(
            pts_proj[pts_proj["idx_orig"].isin(gdf_join.index[faltan])],
            pol_proj[["zona", "subzona", "geometry"]],
            how="left", predicate="intersects"
        ).drop_duplicates(subset="idx_orig").set_index("idx_orig")
        for col in ["zona", "subzona"]:
            gdf_join.loc[faltan, col] = (
                gdf_join.loc[faltan, col].fillna(join_buff[col])
            )

    df_final = df.join(gdf_join[["zona","subzona"]])

    # ----------- preparar Excel en memoria ----------
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False)
    buffer.seek(0)

    stats = {
        "total": len(df),
        "con_zona": df_final.zona.notna().sum(),
        "sin_zona": df_final.zona.isna().sum(),
        "api_calls": api_calls,
        "cache_hits": cache_hits,
    }
    return buffer, stats


# -------------------------- Interfaz UI ---------------------------
uploaded_file = st.file_uploader("⬆️  Cargar Excel de direcciones",
                                 type=["xlsx", "xls"])

if uploaded_file and (api_key or os.getenv("GOOGLE_MAPS_API_KEY")):
    if st.button(PROCESS_BTN_LABEL, type="primary"):
        with st.spinner("Procesando… esto puede tardar unos minutos ⏳"):
            excel_buffer, stats = process_file(uploaded_file, api_key or os.getenv("GOOGLE_MAPS_API_KEY"))
        st.success("¡Proceso completado!")
        st.metric("Direcciones procesadas", stats["total"])
        st.metric("Direcciones con zona",   stats["con_zona"])
        st.metric("Direcciones sin zona",   stats["sin_zona"])
        st.metric("Consultas nuevas API",   stats["api_calls"])
        st.metric("Consultas desde caché",  stats["cache_hits"])

        st.download_button(
            label="📥 Descargar direcciones_geocodificadas.xlsx",
            data=excel_buffer,
            file_name="direcciones_geocodificadas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Cargue un archivo y escriba su API-Key para habilitar el botón 'Procesar'.")
