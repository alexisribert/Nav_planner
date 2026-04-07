import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
import io
import math
from datetime import datetime

# ==========================================
# 1. DONNÉES DES AVIONS & CARBURANT
# ==========================================
DENSITE_AVGAS = 0.72  
CAPACITE_MAX_CARBURANT_L = 118.0  

ENVELOPPE_CG = [0.22, 0.22, 0.32, 0.46, 0.46, 0.22]
ENVELOPPE_MASSE = [500, 580, 780, 780, 500, 500]

AIRCRAFT_DATA = {
    "D-EVTL": {
        "masse_vide": 557.58, "bras_vide": 0.276,   
        "bras": {"pilote_pax": 0.45, "carburant": 1.1, "bagages": 1.2},
        "masse_max": 780, "vp_croisiere_kt": 100, "deviation": 1 
    },
    "F-HNBB": {
        "masse_vide": 541.90, "bras_vide": 0.261,  
        "bras": {"pilote_pax": 0.45, "carburant": 1.1, "bagages": 1.2},
        "masse_max": 780, "vp_croisiere_kt": 100, "deviation": -1
    }
}

# ==========================================
# 2. BASE DE DONNÉES ET GÉOMÉTRIE
# ==========================================
@st.cache_data(show_spinner=False)
def charger_base_aerodromes():
    """Télécharge la base mondiale des aérodromes (exécuté une seule fois)."""
    try:
        url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
        df = pd.read_csv(url)
        # On garde uniquement l'identifiant (OACI) et les coordonnées
        return df[['ident', 'latitude_deg', 'longitude_deg']].set_index('ident').to_dict('index')
    except Exception:
        # Fallback en cas de problème de connexion (on met Lille par défaut)
        return {"LFQQ": {"latitude_deg": 50.5619, "longitude_deg": 3.0894}}

def calculer_distance_et_cap(lat1, lon1, lat2, lon2):
    """Calcule la distance en Nm et la Route Vraie entre deux points GPS."""
    R = 3440.065  # Rayon de la Terre en milles nautiques (Nm)
    
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    
    # Distance (Formule de Haversine)
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    # Cap (Route Vraie)
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    cap_vrai = (math.degrees(math.atan2(y, x)) + 360) % 360
    
    return distance, cap_vrai

def calculer_triangle_vitesses(rv_deg, vp_kt, vent_dir_deg, vent_force_kt):
    """Calcule le cap vrai, la dérive et la vitesse sol"""
    rv_rad = math.radians(rv_deg)
    vent_dir_rad = math.radians(vent_dir_deg)
    
    angle_au_vent = vent_dir_rad - rv_rad
    vent_traversier = vent_force_kt * math.sin(angle_au_vent)
    vent_effectif = vent_force_kt * math.cos(angle_au_vent)
    
    try:
        derive_rad = math.asin(vent_traversier / vp_kt)
    except ValueError:
        derive_rad = 0
    
    derive_deg = math.degrees(derive_rad)
    cv_deg = (rv_deg + derive_deg) % 360
    vs_kt = vp_kt * math.cos(derive_rad) - vent_effectif
    
    return cv_deg, derive_deg, vs_kt

def calculer_centrage(avion, masse_pilotes, masse_bagages, masse_carburant):
    data = AIRCRAFT_DATA[avion]
    masse_totale = data["masse_vide"] + masse_pilotes + masse_bagages + masse_carburant
    moment_total = (data["masse_vide"] * data["bras_vide"] + 
                    masse_pilotes * data["bras"]["pilote_pax"] + 
                    masse_bagages * data["bras"]["bagages"] + 
                    masse_carburant * data["bras"]["carburant"])
    cg = moment_total / masse_totale if masse_totale > 0 else 0
    return masse_totale, cg

# Chargement de la base de données au démarrage
DB_AERODROMES = charger_base_aerodromes()

# ==========================================
# 3. INTERFACE STREAMLIT
# ==========================================
st.set_page_config(page_title="EFB VFR - HR200", layout="wide")
st.title("🛩️ EFB Aéroclub - HR200-120")

# --- SIDEBAR : CONFIGURATION DU VOL ---
st.sidebar.header("Paramètres du vol")
avion_choisi = st.sidebar.selectbox("Sélectionnez l'avion", list(AIRCRAFT_DATA.keys()))
mode = st.sidebar.radio("Mode de vol", ["Local", "Navigation"])
st.sidebar.markdown("---")

points_noms = []

if mode == "Local":
    dep = st.sidebar.text_input("Aérodrome (Code OACI)", "LFQQ").upper()
    points_noms = [dep, dep]
else:
    dep = st.sidebar.text_input("Départ (OACI)", "LFQQ").upper()
    nb_dest = st.sidebar.number_input("Nombre de points intermédiaires", min_value=1, max_value=10, value=1)
    
    points_noms.append(dep)
    for i in range(int(nb_dest)):
        dest = st.sidebar.text_input(f"Point {i+1} (OACI ou Nom)", f"PT{i+1}").upper()
        points_noms.append(dest)
    
    arr = st.sidebar.text_input("Arrivée (OACI)", "LFQQ").upper()
    points_noms.append(arr)

# --- ONGLETS PRINCIPAUX ---
tab_centrage, tab_nav, tab_carte = st.tabs(["⚖️ Devis de Centrage", "🗺️ Log de Navigation", "📍 Carte VFR"])

# ------------------------------------------
# ONGLET 1 : DEVIS DE CENTRAGE (Inchangé)
# ------------------------------------------
with tab_centrage:
    st.subheader("Masses et chargement")
    st.info(f"Capacité max : {CAPACITE_MAX_CARBURANT_L} L. Densité : {DENSITE_AVGAS} kg/L.")
    
    resultats_centrage = []
    colonnes_centrage = st.columns(len(points_noms))

    for i, pt_nom in enumerate(points_noms):
        with colonnes_centrage[i]:
            st.markdown(f"**{pt_nom}**")
            pax = st.number_input(f"Pilote + Pax (kg)", min_value=0.0, value=140.0, step=1.0, key=f"pax_{i}")
            bag = st.number_input(f"Bagages (kg)", min_value=0.0, max_value=35.0, value=0.0, step=1.0, key=f"bag_{i}")
            carb_litres = st.number_input(f"Carburant (L)", min_value=0.0, max_value=CAPACITE_MAX_CARBURANT_L, value=70.0, step=1.0, key=f"carb_{i}")
            
            carb_kg = carb_litres * DENSITE_AVGAS
            masse, cg = calculer_centrage(avion_choisi, pax, bag, carb_kg)
            resultats_centrage.append({"Etape": pt_nom, "Masse": masse, "CG": cg})

    st.markdown("---")
    col_graph, col_alertes = st.columns([2, 1])
    
    with col_graph:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(ENVELOPPE_CG, ENVELOPPE_MASSE, 'r-', linewidth=2, label="Enveloppe autorisée")
        ax.fill(ENVELOPPE_CG, ENVELOPPE_MASSE, 'red', alpha=0.1)
        
        df_res_centrage = pd.DataFrame(resultats_centrage)
        colors = ['blue', 'purple', 'orange', 'green', 'brown', 'black']
        
        for i in range(len(df_res_centrage)):
            cg_actuel = df_res_centrage.loc[i, "CG"]
            masse_actuelle = df_res_centrage.loc[i, "Masse"]
            ax.plot(cg_actuel, masse_actuelle, marker='o', markersize=8, color=colors[i % len(colors)])
            ax.text(cg_actuel + 0.002, masse_actuelle + 5, df_res_centrage.loc[i, "Etape"], fontsize=9)
            if i < len(df_res_centrage) - 1:
                ax.annotate('', xy=(df_res_centrage.loc[i+1, "CG"], df_res_centrage.loc[i+1, "Masse"]), 
                            xytext=(cg_actuel, masse_actuelle), arrowprops=dict(arrowstyle="->", color='gray', ls='--'))
        
        ax.set_xlim(0.18, 0.50)
        ax.set_ylim(480, 800)
        ax.set_xlabel("Centrage (m)")
        ax.set_ylabel("Masse (kg)")
        ax.grid(True, linestyle=':', alpha=0.7)
        st.pyplot(fig)

    with col_alertes:
        for i, row in df_res_centrage.iterrows():
            if row["Masse"] > AIRCRAFT_DATA[avion_choisi]["masse_max"]:
                st.error(f"⚠️ Dépassement masse max à : {row['Etape']}")
            if row["CG"] < 0.22 or row["CG"] > 0.46:
                st.error(f"⚠️ Centrage hors limites absolues à : {row['Etape']}")

# ------------------------------------------
# ONGLET 2 : LOG DE NAVIGATION
# ------------------------------------------
with tab_nav:
    col_v, col_dec = st.columns(2)
    vp_nav = col_v.number_input("Vitesse Propre (Vp) en kt", value=AIRCRAFT_DATA[avion_choisi]["vp_croisiere_kt"])
    declinaison = col_dec.number_input("Déclinaison Magnétique (° E/W, ex: -1 pour 1°W)", value=0.0)
    
    st.markdown("### 📍 Coordonnées des points de vol")
    st.info("Les coordonnées des codes OACI valides sont récupérées automatiquement. Pour les autres points (ex: points VFR), modifiez les coordonnées manuellement en degrés décimaux.")
    
    # Dictionnaire pour stocker les coordonnées finales choisies par l'utilisateur
    coords_vol = {}
    
    cols_coords = st.columns(len(points_noms))
    for i, pt_nom in enumerate(points_noms):
        with cols_coords[i]:
            st.markdown(f"**{pt_nom}**")
            # Chercher dans la base de données OACI
            lat_defaut, lon_defaut = 0.0, 0.0
            if pt_nom in DB_AERODROMES:
                lat_defaut = DB_AERODROMES[pt_nom]["latitude_deg"]
                lon_defaut = DB_AERODROMES[pt_nom]["longitude_deg"]
                st.success("OACI Trouvé")
            else:
                st.warning("Saisie manuelle")
                
            lat = st.number_input("Latitude (°)", value=lat_defaut, format="%.5f", key=f"lat_{i}")
            lon = st.number_input("Longitude (°)", value=lon_defaut, format="%.5f", key=f"lon_{i}")
            coords_vol[i] = {"nom": pt_nom, "lat": lat, "lon": lon}

    st.markdown("---")
    st.markdown("### 🧭 Calcul des Branches")
    
    log_nav_data = []
    
    for i in range(len(points_noms) - 1):
        pt_dep = coords_vol[i]
        pt_arr = coords_vol[i+1]
        
        # Le calcul de Route Vraie et Distance se fait tout seul maintenant !
        dist_calc, rv_calc = calculer_distance_et_cap(pt_dep["lat"], pt_dep["lon"], pt_arr["lat"], pt_arr["lon"])
        
        with st.expander(f"Branche {i+1} : {pt_dep['nom']} ➔ {pt_arr['nom']}", expanded=True):
            col1, col2, col3, col4 = st.columns(4)
            
            st.write(f"📏 **Route Vraie (Rv) : {int(rv_calc)}°** | **Distance : {round(dist_calc, 1)} Nm**")
            
            vent_dir = col1.number_input(f"Vent Dir (°)", min_value=0, max_value=360, value=0, key=f"w_dir_{i}")
            vent_force = col2.number_input(f"Vent Force (kt)", min_value=0, value=0, key=f"w_force_{i}")
            
            # Application de la trigonométrie
            cv, derive, vs = calculer_triangle_vitesses(rv_calc, vp_nav, vent_dir, vent_force)
            cm = (cv - declinaison) % 360
            cc = (cm - AIRCRAFT_DATA[avion_choisi]["deviation"]) % 360
            temps_vol_min = (dist_calc / vs) * 60 if vs > 0 else 0
            
            log_nav_data.append({
                "De": pt_dep["nom"], "Vers": pt_arr["nom"],
                "Rv (°)": int(rv_calc), "Dist (Nm)": round(dist_calc, 1),
                "Vent": f"{int(vent_dir)}° / {int(vent_force)}kt",
                "Cv (°)": int(cv), "Cm (°)": int(cm), "Cc (°)": int(cc),
                "Vs (kt)": int(vs), "Temps (min)": int(temps_vol_min)
            })
            
    st.markdown("#### Tableau de Marche (Log de Nav)")
    df_log = pd.DataFrame(log_nav_data)
    st.dataframe(df_log, use_container_width=True)

# ------------------------------------------
# ONGLET 3 : CARTE VFR
# ------------------------------------------
with tab_carte:
    st.subheader("Visualisation du trajet")
    st.info("Ici apparaîtra la carte interactive.")
