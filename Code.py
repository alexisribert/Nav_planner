import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
import io
import math
from datetime import datetime
import folium
from streamlit_folium import st_folium


# ==========================================
# 1. DONNÉES DES AVIONS & CARBURANT
# ==========================================
DENSITE_AVGAS = 0.72  
CAPACITE_MAX_CARBURANT_L = 118.0  
CONSO_BASE_L_H = 25.0
MARGE_CONSO = 1.10 # +10% de marge de sécurité
CONSO_EFFECTIVE_L_H = CONSO_BASE_L_H * MARGE_CONSO

ENVELOPPE_CG = [0.22, 0.22, 0.32, 0.46, 0.46, 0.22]
ENVELOPPE_MASSE = [500, 580, 780, 780, 500, 500]

AIRCRAFT_DATA = {
    "D-EVTL": {
        "masse_vide": 557.58, "bras_vide": 0.276,   
        "bras": {"pilote_pax": 0.45, "carburant": 1.1, "bagages": 1.2},
        "masse_max": 780, "vp_croisiere_kmh": 175, 
        "table_deviation": {
            0: 0, 30: 0, 60: 0, 90: 0, 120: 0, 150: 0, 
            180: 0, 210: 0, 240: 0, 270: 0, 300: 0, 330: 0, 360: 0
        }
    },
    "F-HNBB": {
        "masse_vide": 541.90, "bras_vide": 0.261,  
        "bras": {"pilote_pax": 0.45, "carburant": 1.1, "bagages": 1.2},
        "masse_max": 780, "vp_croisiere_kmh": 175,
        "table_deviation": {
            0: 0, 30: -1, 60: 0, 90: -1, 120: -2, 150: -1,
            180: 1, 210: 0, 240: 0, 270: 1, 300: 0, 330: 1, 360: 0 
        }
    }
}

# ==========================================
# 2. BASE DE DONNÉES ET GÉOMÉTRIE
# ==========================================
@st.cache_data(show_spinner=False)
def charger_base_aerodromes():
    try:
        url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
        df = pd.read_csv(url)
        return df[['ident', 'latitude_deg', 'longitude_deg']].set_index('ident').to_dict('index')
    except Exception:
        return {"LFQQ": {"latitude_deg": 50.5619, "longitude_deg": 3.0894}}

def calculer_distance_et_cap(lat1, lon1, lat2, lon2):
    R = 3440.065  
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    cap_vrai = (math.degrees(math.atan2(y, x)) + 360) % 360
    
    return distance, cap_vrai

def calculer_triangle_vitesses(rv_deg, vp_kt, vent_dir_deg, vent_force_kt):
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

def interpoler_cap_compas(cm, table_deviation):
    cm_modulo = cm % 360
    if cm_modulo == 0 and cm > 0:
        cm_cible = 360
    else:
        cm_cible = cm_modulo
        
    caps = sorted(list(table_deviation.keys()))
    
    if cm_cible in caps:
        deviation = table_deviation[cm_cible]
    else:
        for i in range(len(caps) - 1):
            if caps[i] < cm_cible < caps[i+1]:
                cm1, cm2 = caps[i], caps[i+1]
                dev1, dev2 = table_deviation[cm1], table_deviation[cm2]
                fraction = (cm_cible - cm1) / (cm2 - cm1)
                deviation = dev1 + fraction * (dev2 - dev1)
                break
                
    cc_final = (cm - deviation) % 360
    return cc_final

def calculer_centrage(avion, masse_pilotes, masse_bagages, masse_carburant):
    data = AIRCRAFT_DATA[avion]
    masse_totale = data["masse_vide"] + masse_pilotes + masse_bagages + masse_carburant
    moment_total = (data["masse_vide"] * data["bras_vide"] + 
                    masse_pilotes * data["bras"]["pilote_pax"] + 
                    masse_bagages * data["bras"]["bagages"] + 
                    masse_carburant * data["bras"]["carburant"])
    cg = moment_total / masse_totale if masse_totale > 0 else 0
    return masse_totale, cg

DB_AERODROMES = charger_base_aerodromes()

# ==========================================
# 3. INTERFACE STREAMLIT
# ==========================================
st.set_page_config(page_title="EFB VFR - HR200", layout="wide")
st.title("🛩️ EFB Aéroclub - HR200-120")

# --- SIDEBAR ---
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

# --- ONGLETS (Nav en premier pour calculer les temps de vol) ---
tab_nav, tab_centrage, tab_carte = st.tabs(["🗺️ Log de Navigation", "⚖️ Devis de Centrage", "📍 Carte VFR"])

# Liste pour stocker le temps de vol de chaque branche (sera utilisée par le centrage)
temps_branches_min = []

# ------------------------------------------
# ONGLET 1 : LOG DE NAVIGATION
# ------------------------------------------
with tab_nav:
    col_v, col_dec = st.columns(2)
    vp_nav_kmh = col_v.number_input("Vitesse Propre (Vp) en km/h", value=AIRCRAFT_DATA[avion_choisi]["vp_croisiere_kmh"])
    declinaison = col_dec.number_input("Déclinaison Magnétique (° E/W, ex: -1 pour 1°W)", value=0.0)
    
    # Conversion Vp en noeuds pour les calculs aéro
    vp_nav_kt = vp_nav_kmh / 1.852 
    
    st.markdown("### 📍 Coordonnées des points de vol")
    
    coords_vol = {}
    cols_coords = st.columns(len(points_noms))
    for i, pt_nom in enumerate(points_noms):
        with cols_coords[i]:
            st.markdown(f"**{pt_nom}**")
            
            lat_defaut, lon_defaut = 0.0, 0.0
            if pt_nom in DB_AERODROMES:
                lat_defaut = DB_AERODROMES[pt_nom]["latitude_deg"]
                lon_defaut = DB_AERODROMES[pt_nom]["longitude_deg"]
                st.success("OACI Trouvé")
            else:
                st.warning("Saisie manuelle")
            
            lat = st.number_input("Latitude (°)", value=lat_defaut, format="%.5f", key=f"lat_{i}_{pt_nom}")
            lon = st.number_input("Longitude (°)", value=lon_defaut, format="%.5f", key=f"lon_{i}_{pt_nom}")
            coords_vol[i] = {"nom": pt_nom, "lat": lat, "lon": lon}

    st.markdown("---")
    st.markdown("### 🧭 Calcul des Branches")
    
    log_nav_data = []
    
    for i in range(len(points_noms) - 1):
        pt_dep = coords_vol[i]
        pt_arr = coords_vol[i+1]
        
        dist_calc, rv_calc = calculer_distance_et_cap(pt_dep["lat"], pt_dep["lon"], pt_arr["lat"], pt_arr["lon"])
        
        with st.expander(f"Branche {i+1} : {pt_dep['nom']} ➔ {pt_arr['nom']}", expanded=True):
            col1, col2 = st.columns(2)
            
            if dist_calc == 0:
                st.info("Point identique ou vol local détecté. Entrez la durée du vol manuellement.")
                temps_vol_min = st.number_input("Durée du vol local (min)", min_value=0, value=45, key=f"tps_local_{i}")
                vent_dir, vent_force, cv, cm, cc, vs = 0, 0, 0, 0, 0, 0
            else:
                st.write(f"📏 **Route Vraie (Rv) : {int(rv_calc)}°** | **Distance : {round(dist_calc, 1)} Nm**")
                vent_dir = col1.number_input(f"Vent Dir (°)", min_value=0, max_value=360, value=0, key=f"w_dir_{i}")
                vent_force = col2.number_input(f"Vent Force (kt)", min_value=0, value=0, key=f"w_force_{i}")
                
                cv, derive, vs = calculer_triangle_vitesses(rv_calc, vp_nav_kt, vent_dir, vent_force)
                cm = (cv - declinaison) % 360
                
                table_dev_avion = AIRCRAFT_DATA[avion_choisi]["table_deviation"]
                cc = interpoler_cap_compas(cm, table_dev_avion)
                
                temps_vol_min = (dist_calc / vs) * 60 if vs > 0 else 0
            
            # On stocke le temps pour le calcul du carburant dans le centrage
            temps_branches_min.append(temps_vol_min)
            
            log_nav_data.append({
                "De": pt_dep["nom"], "Vers": pt_arr["nom"],
                "Rv (°)": int(rv_calc) if dist_calc > 0 else "-", 
                "Dist (Nm)": round(dist_calc, 1),
                "Vent": f"{int(vent_dir)}° / {int(vent_force)}kt" if dist_calc > 0 else "-",
                "Cv (°)": int(cv) if dist_calc > 0 else "-", 
                "Cm (°)": int(cm) if dist_calc > 0 else "-", 
                "Cc (°)": int(cc) if dist_calc > 0 else "-",
                "Vs (kt)": int(vs) if dist_calc > 0 else "-", 
                "Temps (min)": int(temps_vol_min)
            })
            
    st.markdown("#### Tableau de Marche (Log de Nav)")
    df_log = pd.DataFrame(log_nav_data)
    st.dataframe(df_log, use_container_width=True)

# ------------------------------------------
# ONGLET 2 : DEVIS DE CENTRAGE
# ------------------------------------------
with tab_centrage:
    st.subheader("Masses et chargement")
    st.info(f"Le carburant aux étapes intermédiaires est calculé automatiquement d'après le Log de Nav (Conso {CONSO_BASE_L_H} L/h + marge, soit {CONSO_EFFECTIVE_L_H:.1f} L/h).")
    
    resultats_centrage = []
    colonnes_centrage = st.columns(len(points_noms))
    
    # Liste pour retenir le carburant restant à chaque étape
    carb_restant_list = []

    for i, pt_nom in enumerate(points_noms):
        with colonnes_centrage[i]:
            st.markdown(f"**{pt_nom}**")
            pax = st.number_input(f"Pilote + Pax (kg)", min_value=0.0, value=140.0, step=1.0, key=f"pax_{i}")
            bag = st.number_input(f"Bagages (kg)", min_value=0.0, max_value=35.0, value=0.0, step=1.0, key=f"bag_{i}")
            
            # Carburant : Saisie manuelle uniquement au départ, calculé ensuite
            if i == 0:
                carb_litres = st.number_input(f"Carburant (L)", min_value=0.0, max_value=CAPACITE_MAX_CARBURANT_L, value=70.0, step=1.0, key=f"carb_{i}")
                carb_restant_list.append(carb_litres)
            else:
                # Consommation sur la branche précédente
                temps_etape_precedente = temps_branches_min[i-1]
                conso_litres = (temps_etape_precedente / 60.0) * CONSO_EFFECTIVE_L_H
                
                # Mise à jour du carburant restant (sans descendre sous zéro)
                carb_litres = max(0.0, carb_restant_list[-1] - conso_litres)
                carb_restant_list.append(carb_litres)
                
                # CORRECTION ICI : Affichage en lecture seule (grisé) avec clé dynamique
                st.text_input(f"Carburant calculé (L)", value=f"{carb_litres:.1f}", disabled=True, key=f"carb_auto_{i}_{carb_litres:.1f}")
            
            # Calcul du centrage
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
# ONGLET 3 : CARTE VFR
# ------------------------------------------
with tab_carte:
    st.subheader("Visualisation de la route sur carte OACI")
    
    # On vérifie qu'on a bien des coordonnées à afficher
    if len(coords_vol) > 1:
        route_coords = [(data["lat"], data["lon"]) for data in coords_vol.values()]
        
        # Calcul du centre de la carte
        avg_lat = sum(p[0] for p in route_coords) / len(route_coords)
        avg_lon = sum(p[1] for p in route_coords) / len(route_coords)
        
        # Création de la carte de base (tiles=None pour ne pas charger OpenStreetMap par défaut)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=8, tiles=None)
        
        # FOND DE CARTE OACI GÉOPORTAIL (SIA / IGN)
        url_oaci = (
            "https://data.geopf.fr/wmts?"
            "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&"
            "LAYER=GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN-OACI&"
            "STYLE=normal&FORMAT=image/jpeg&"
            "TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
        )
        
        folium.TileLayer(
            tiles=url_oaci,
            attr='&copy; <a href="https://www.ign.fr/">IGN</a> - SIA',
            name='Carte VFR OACI',
            max_zoom=11,   # La carte OACI n'existe pas en zoom trop rapproché
            min_zoom=6     # Ni en zoom trop éloigné
        ).add_to(m)
        
        # Tracé de la ligne de la route (Magenta pour imiter le GPS)
        folium.PolyLine(
            route_coords, 
            color="#FF00FF", 
            weight=5, 
            opacity=0.9,
            dash_array="10"
        ).add_to(m)
        
        # Ajout des marqueurs pour chaque point
        for i, (idx, data) in enumerate(coords_vol.items()):
            pt_nom = data["nom"]
            lat = data["lat"]
            lon = data["lon"]
            
            if i == 0:
                couleur = "green"
                icone = "plane-departure"
            elif i == len(coords_vol) - 1:
                couleur = "red"
                icone = "plane-arrival"
            else:
                couleur = "blue"
                icone = "map-marker"
                
            folium.Marker(
                location=[lat, lon],
                popup=f"<b>{pt_nom}</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}",
                tooltip=pt_nom,
                icon=folium.Icon(color=couleur, icon=icone, prefix='fa')
            ).add_to(m)
            
        # Affichage dynamique dans Streamlit
        st_folium(m, width=1200, height=600, returned_objects=[])
        
    else:
        st.warning("Veuillez configurer au moins un départ et une arrivée dans les paramètres du vol.")

