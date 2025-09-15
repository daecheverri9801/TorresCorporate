# ================================================================
# Streamlit App :  Geocodificar Direcciones – Torres Corporate
# ================================================================
import os, zipfile, shutil, time, warnings, io
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import googlemaps
import streamlit as st
from PIL import Image
warnings.filterwarnings("ignore", category=UserWarning)

# ------------------- CONFIGURACIÓN GENERAL ----------------------
API_KEY   = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyCkZG7fbor17mhs3NLjaThcChO-Pav67gA")
DATA_DIR  = "data"
CACHE_FILE = "cache_geocoding.csv"
KMZ_FILES = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.lower().endswith(".kmz")]
LOGO_PATH = "assets/logo_torres.jpg"
LOGO_WIDTH = 120

st.set_page_config(page_title="Torres Corporate · Geolocalización",
                   page_icon="🚚", layout="wide",
                   initial_sidebar_state="collapsed")

# --------------------------- ESTILOS ----------------------------
st.markdown(
    """
    <style>
    :root{
        --primary:#005bea;
        --secondary:#00c6fb;
        --bg:#f7faff;
        --text:#10243c;
        --textupdate: #ffffff;
    }
    html, body, section.main > div{background:var(--bg);}
    body, p, div, span, li{color:var(--text)!important;}
    *{font-family:'Inter',sans-serif;}

    .titulo{font-size:2.3rem;font-weight:700;color:var(--primary);margin:0 0 .25rem 0;}
    .sub{font-size:1.05rem;margin-bottom:1.2rem;}

    hr.modern{border:none;height:4px;
              background:linear-gradient(90deg,var(--primary) 0%,var(--secondary) 100%);
              margin:-4px 0 28px 0;border-radius:3px;}

    /* botones */
    .stButton>button{background:var(--primary);color:#fff;border:none;border-radius:6px;
                     padding:0.55rem 1.2rem;font-weight:600;font-size:0.95rem;transition:.2s;}
    .stButton>button:hover{background:#0047c2;}

    .stDownloadButton>button{background:var(--secondary);color:#fff!important;border:none;border-radius:6px;
                             padding:0.55rem 1.2rem;font-weight:600;transition:.2s;}
    .stDownloadButton>button:hover{background:#00a0ce;}

    /* drop-zone azul */
    div[data-testid="stFileUploaderDropzone"]{
        border:2px dashed var(--primary)!important;
        background:#eaf2ff!important;
        color:var(--text)!important;
    }
    div[data-testid="stFileUploader"] > label{color:var(--text);font-weight:600;}

    /* caja de métrica con tooltip */
    .metric-box{background:#fff;border:1px solid var(--primary);border-radius:6px;
                padding:10px 12px;text-align:center;width:100%;position:relative;}
    .metric-label{font-size:0.85rem;color:var(--text);font-weight:500;}
    .metric-value{font-size:1.4rem;font-weight:700;color:var(--primary);margin-top:2px;}

    /* icono + burbuja */
    .tooltip-icon{cursor:help;margin-left:4px;color:var(--primary);font-weight:700;}
    .metric-box .tooltip-icon::after{
        content: attr(data-tip);
        position:absolute;left:50%;bottom:125%;transform:translateX(-50%);
        background:#333;color:#fff;padding:6px 8px;border-radius:4px;
        white-space:nowrap;font-size:0.75rem;opacity:0;pointer-events:none;
        transition:opacity .15s ease;
    }
    .metric-box .tooltip-icon:hover::after{opacity:1;}
    </style>
    """,
    unsafe_allow_html=True
)

# ----------------------- BANNER CON LOGO ------------------------
col_logo, col_title = st.columns([1,4])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(Image.open(LOGO_PATH), width=LOGO_WIDTH)
with col_title:
    st.markdown('<div class="titulo">🚚 Torres Corporate</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub">Soluciones logísticas</div>', unsafe_allow_html=True)
st.markdown('<hr class="modern">', unsafe_allow_html=True)

# --------------------- FUNCIONES AUXILIARES ---------------------
def load_cache():
    if os.path.exists(CACHE_FILE) and os.path.getsize(CACHE_FILE)>0:
        return pd.read_csv(CACHE_FILE)
    return pd.DataFrame(columns=["full_address","latitude","longitude","geocode_status"])
cache_df = load_cache()

@st.cache_resource(show_spinner=False)
def load_polygons():
    def kmz_to_gdf(path):
        zona=os.path.basename(path).replace(".kmz",""); tmp=path.replace(".kmz","_tmp")
        with zipfile.ZipFile(path) as zf: zf.extractall(tmp)
        kml=next((f for f in os.listdir(tmp) if f.endswith(".kml")),None)
        if not kml: shutil.rmtree(tmp); return gpd.GeoDataFrame()
        gdf=gpd.read_file(os.path.join(tmp,kml), driver="KML")
        gdf["zona"]=zona
        gdf["subzona"]=gdf["Name"].fillna(gdf.get("Description")).fillna("Sin_nombre")
        shutil.rmtree(tmp); return gdf
    return pd.concat([kmz_to_gdf(f) for f in KMZ_FILES],ignore_index=True).to_crs(4326)

def build_address(r):
    parts=[str(r.get("Buyer Address1","")).strip(),
           str(r.get("Buyer Address1 Number","")).strip(),
           str(r.get("Buyer City","")).strip(),"Colombia"]
    return ", ".join([p for p in parts if p and p.lower()!="nan"])

def geocode_enhanced(cli,address,retries=3):
    for _ in range(retries):
        try:
            res=cli.geocode(address,region="co",language="es")
            if res: loc=res[0]["geometry"]["location"]; return loc["lat"],loc["lng"],"completa"
        except Exception: time.sleep(0.8)
    try:
        city=address.split(",")[-2]+", Colombia"
        res=cli.geocode(city,region="co",language="es")
        if res: loc=res[0]["geometry"]["location"]; return loc["lat"],loc["lng"],"ciudad"
    except Exception: pass
    return None,None,"fallida"

def geocode_with_cache(cli,address):
    hit=cache_df.loc[cache_df.full_address==address]
    if not hit.empty:
        r=hit.iloc[0]; return r.latitude,r.longitude,r.geocode_status,True
    lat,lon,stat=geocode_enhanced(cli,address)
    cache_df.loc[len(cache_df)]=[address,lat,lon,stat]
    return lat,lon,stat,False

def process_file(f):
    df=pd.read_excel(f).copy().reset_index(drop=True)
    df["full_address"]=df.apply(build_address,axis=1)
    cli=googlemaps.Client(API_KEY)
    lat,lon,status=[],[],[]; api_calls=cache_hits=0
    prog=st.progress(0)
    for i,a in enumerate(df.full_address):
        la,lo,stt,hit=geocode_with_cache(cli,a)
        lat.append(la); lon.append(lo); status.append(stt)
        cache_hits+=hit; api_calls+= (not hit); prog.progress((i+1)/len(df))
    prog.empty()
    df["latitude"]=lat; df["longitude"]=lon; df["geocode_status"]=status
    cache_df.to_csv(CACHE_FILE,index=False)

    gdf_pol=load_polygons()
    gdf_pts=gpd.GeoDataFrame(df[df.latitude.notna() & df.longitude.notna()].reset_index().rename(columns={'index':'idx'}),
                             geometry=[Point(xy) for xy in zip(df.longitude,df.latitude)], crs=4326)
    join=gpd.sjoin(gdf_pts,gdf_pol[['zona','subzona','geometry']],how='left',predicate='within')\
          .drop_duplicates(subset='idx').set_index('idx')
    df=df.join(join[['zona','subzona']])

    buf=io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w: df.to_excel(w,index=False)
    buf.seek(0)
    return buf, dict(total=len(df),con_zona=df.zona.notna().sum(),
                     sin_zona=df.zona.isna().sum(),api_calls=api_calls,cache_hits=cache_hits)

# --------------------------- INTERFAZ ---------------------------
tabs=st.tabs(["🗺️ Geolocalización"])
with tabs[0]:
    file=st.file_uploader("⬆️  Cargar Excel de direcciones",
                          type=["xlsx","xls"], accept_multiple_files=False)

    if file and st.button("🚀 Procesar y descargar", type="primary"):
        with st.spinner("Geocodificando…"):
            result, stats = process_file(file)

        name=Path(file.name)
        download_name=f"{name.stem}_Geolocalizado{name.suffix}"
        st.success("¡Listo!")

        # métricas con tooltip propio
        col1,col2,col3,col4,col5=st.columns(5)
        data=[("Total", stats["total"], "Total de Direcciones Encontradas"),
              ("Con zona", stats["con_zona"], "Cantidad de Direcciones Geolocalizadas"),
              ("Sin zona", stats["sin_zona"], "Cantidad de Direcciones no Geolocalizadas"),
              ("API nuevas", stats["api_calls"], "Cantidad de Geolocalizaciones realizadas desde la API"),
              ("Desde caché", stats["cache_hits"], "Cantidad de Geolocalizaciones realizadas desde Caché")]
        for col,(lbl,val,tip) in zip([col1,col2,col3,col4,col5], data):
            col.markdown(
                f'''
                <div class="metric-box">
                  <div class="metric-label">{lbl}
                    <span class="tooltip-icon" data-tip="{tip}">ℹ️</span>
                  </div>
                  <div class="metric-value">{val}</div>
                </div>
                ''',
                unsafe_allow_html=True
            )

        st.download_button("📥 Descargar resultado", data=result,
                           file_name=download_name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif not file:
        st.info("Arrastra o selecciona tu archivo para habilitar el botón.")