import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
import math
import uuid
import folium
from streamlit_folium import st_folium
from datetime import datetime
import pygeomag

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
        "table_deviation": {0: 0, 30: 0, 60: 0, 90: 0, 120: 0, 150: 0, 180: 0, 210: 0, 240: 0, 270: 0, 300: 0, 330: 0, 360: 0}
    },
    "F-HNBB": {
        "masse_vide": 541.90, "bras_vide": 0.261,  
        "bras": {"pilote_pax": 0.45, "carburant": 1.1, "bagages": 1.2},
        "masse_max": 780, "vp_croisiere_kmh": 175,
        "table_deviation": {0: 0, 30: -1, 60: 0, 90: -1, 120: -2, 150: -1, 180: 1, 210: 0, 240: 0, 270: 1, 300: 0, 330: 1, 360: 0}
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

DB_AERODROMES = charger_base_aerodromes()

def create_point(nom, lat, lon):
    return {"id": str(uuid.uuid4()), "nom": nom, "lat": lat, "lon": lon}

def resolve_oaci(oaci):
    if oaci in DB_AERODROMES:
        return create_point(oaci, DB_AERODROMES[oaci]["latitude_deg"], DB_AERODROMES[oaci]["longitude_deg"])
    return create_point(oaci if oaci else "WPT", 0.0, 0.0)

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
    rv_rad, vent_dir_rad = math.radians(rv_deg), math.radians(vent_dir_deg)
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
    cm_cible = 360 if (cm % 360 == 0 and cm > 0) else cm % 360
    caps = sorted(list(table_deviation.keys()))
    if cm_cible in caps:
        deviation = table_deviation[cm_cible]
    else:
        for i in range(len(caps) - 1):
            if caps[i] < cm_cible < caps[i+1]:
                cm1, cm2 = caps[i], caps[i+1]
                dev1, dev2 = table_deviation[cm1], table_deviation[cm2]
                deviation = dev1 + ((cm_cible - cm1) / (cm2 - cm1)) * (dev2 - dev1)
                break
    return (cm - deviation) % 360

def calculer_declinaison(lat, lon):
    """Calcule la déclinaison magnétique exacte via le modèle géomagnétique WMM"""
    try:
        geo_mag = pygeomag.GeoMag()
        now = datetime.now()
        # L'API a besoin de l'année au format décimal (ex: 2024.3)
        annee_decimale = now.year + (now.timetuple().tm_yday / 365.25)
        # Alt = 0 (Niveau de la mer, la différence est négligeable pour le VFR)
        result = geo_mag.calculate(glat=lat, glon=lon, alt=0, time=annee_decimale)
        return result.d
    except Exception:
        return 0.0 # En cas d'erreur, on part du principe qu'elle est nulle.

def calculer_centrage(avion, masse_pilotes, masse_bagages, masse_carburant):
    data = AIRCRAFT_DATA[avion]
    masse_totale = data["masse_vide"] + masse_pilotes + masse_bagages + masse_carburant
    moment_total = (data["masse_vide"] * data["bras_vide"] + 
                    masse_pilotes * data["bras"]["pilote_pax"] + 
                    masse_bagages * data["bras"]["bagages"] + 
                    masse_carburant * data["bras"]["carburant"])
    return masse_totale, (moment_total / masse_totale if masse_totale > 0 else 0)

# ==========================================
# 3. INITIALISATION DU SESSION STATE
# ==========================================
st.set_page_config(page_title="EFB VFR - HR200", layout="wide")

if "route" not in st.session_state:
    st.session_state.route = [resolve_oaci("LFQQ"), resolve_oaci("LFQQ")]
if "last_map_added" not in st.session_state:
    st.session_state.last_map_added = None

# ==========================================
# 4. BARRE LATÉRALE (SIDEBAR)
# ==========================================
st.sidebar.title("🛩️ EFB Aéroclub")
avion_choisi = st.sidebar.selectbox("Avion sélectionné", list(AIRCRAFT_DATA.keys()))

st.sidebar.markdown("---")
st.sidebar.header("1. Initialiser la Route")
st.sidebar.info("Construisez la base OACI ici. Vous pourrez insérer d'autres points plus tard directement sur la carte.")

dep_oaci = st.sidebar.text_input("Départ (OACI)", "LFQQ").upper()
inter_oaci = st.sidebar.text_input("Étapes (OACI, ex: LFPO, LFAQ)", "").upper()
arr_oaci = st.sidebar.text_input("Arrivée (OACI)", "LFQQ").upper()

if st.sidebar.button("Générer la route OACI", use_container_width=True):
    new_route = [resolve_oaci(dep_oaci)]
    if inter_oaci:
        for pt in inter_oaci.split(","):
            if pt.strip():
                new_route.append(resolve_oaci(pt.strip()))
    new_route.append(resolve_oaci(arr_oaci))
    st.session_state.route = new_route
    st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🗑️ Vider la route (Repartir à zéro)", use_container_width=True):
    st.session_state.route = []
    st.rerun()

# ==========================================
# 5. ONGLETS PRINCIPAUX
# ==========================================
tab_nav, tab_carte, tab_centrage = st.tabs(["🗺️ Log de Navigation", "📍 Carte Interactive", "⚖️ Devis de Centrage"])

temps_branches_min = [] 

# ------------------------------------------
# ONGLET 1 : LOG DE NAVIGATION
# ------------------------------------------
with tab_nav:
    # On a supprimé le champ de déclinaison manuelle, on garde juste la vitesse propre
    vp_nav_kmh = st.number_input("Vitesse Propre (Vp) en km/h", value=AIRCRAFT_DATA[avion_choisi]["vp_croisiere_kmh"])
    vp_nav_kt = vp_nav_kmh / 1.852 
    
    st.markdown("### 📍 Éditeur de la route")
    
    if len(st.session_state.route) == 0:
        st.warning("La route est vide. Utilisez le menu de gauche pour l'initialiser.")
    else:
        for i in range(0, len(st.session_state.route), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(st.session_state.route):
                    pt = st.session_state.route[i+j]
                    with cols[j]:
                        with st.container(border=True):
                            st.markdown(f"**Étape {i+j+1}**")
                            n_nom = st.text_input("Nom", value=pt["nom"], key=f"nom_{pt['id']}")
                            n_lat = st.number_input("Lat", value=pt["lat"], format="%.5f", key=f"lat_{pt['id']}")
                            n_lon = st.number_input("Lon", value=pt["lon"], format="%.5f", key=f"lon_{pt['id']}")
                            
                            st.session_state.route[i+j]["nom"] = n_nom
                            st.session_state.route[i+j]["lat"] = n_lat
                            st.session_state.route[i+j]["lon"] = n_lon
                            
                            if st.button("🗑️ Supprimer", key=f"del_{pt['id']}", use_container_width=True):
                                st.session_state.route.pop(i+j)
                                st.rerun()

    st.markdown("---")
    st.markdown("### 🧭 Calcul des Branches")
    
    log_nav_data = []
    for i in range(len(st.session_state.route) - 1):
        pt_dep = st.session_state.route[i]
        pt_arr = st.session_state.route[i+1]
        
        dist_calc, rv_calc = calculer_distance_et_cap(pt_dep["lat"], pt_dep["lon"], pt_arr["lat"], pt_arr["lon"])
        
        with st.expander(f"Branche {i+1} : {pt_dep['nom']} ➔ {pt_arr['nom']}", expanded=True):
            col1, col2 = st.columns(2)
            
            if dist_calc == 0:
                st.info("Vol local détecté (Distance 0). Entrez la durée du vol manuellement.")
                temps_vol_min = st.number_input("Durée du vol local (min)", min_value=0, value=45, key=f"tps_local_{pt_dep['id']}")
                vent_dir, vent_force, cv, cm, cc, vs, declinaison = 0, 0, 0, 0, 0, 0, 0
            else:
                # Calcul de la déclinaison au milieu de la branche
                lat_milieu = (pt_dep["lat"] + pt_arr["lat"]) / 2.0
                lon_milieu = (pt_dep["lon"] + pt_arr["lon"]) / 2.0
                declinaison = calculer_declinaison(lat_milieu, lon_milieu)
                
                # Affichage des infos incluant la déclinaison calculée
                st.write(f"📏 **Route Vraie (Rv) : {int(rv_calc)}°** | **Distance : {round(dist_calc, 1)} Nm** | **Déclinaison locale : {declinaison:.1f}°**")
                
                vent_dir = col1.number_input(f"Vent Dir (°)", min_value=0, max_value=360, value=0, key=f"wdir_{pt_dep['id']}")
                vent_force = col2.number_input(f"Vent Force (kt)", min_value=0, value=0, key=f"wforce_{pt_dep['id']}")
                
                cv, derive, vs = calculer_triangle_vitesses(rv_calc, vp_nav_kt, vent_dir, vent_force)
                
                # Application de la déclinaison calculée automatiquement
                cm = (cv - declinaison) % 360
                
                table_dev_avion = AIRCRAFT_DATA[avion_choisi]["table_deviation"]
                cc = interpoler_cap_compas(cm, table_dev_avion)
                temps_vol_min = (dist_calc / vs) * 60 if vs > 0 else 0
            
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
            
    if len(log_nav_data) > 0:
        st.markdown("#### Tableau de Marche (Log de Nav)")
        st.dataframe(pd.DataFrame(log_nav_data), use_container_width=True)

# ------------------------------------------
# ONGLET 2 : CARTE VFR (AJOUT INTERACTIF)
# ------------------------------------------
with tab_carte:
    st.subheader("Visualisation et Ajout de points")
    st.info("Cliquez n'importe où sur la carte pour insérer un nouveau point dans votre log de navigation.")
    
    route_coords = [(pt["lat"], pt["lon"]) for pt in st.session_state.route]
    
    if len(route_coords) > 0:
        avg_lat = sum(p[0] for p in route_coords) / len(route_coords)
        avg_lon = sum(p[1] for p in route_coords) / len(route_coords)
    else:
        avg_lat, avg_lon = 46.5, 2.5 
        
    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=8, tiles=None)
    
    folium.TileLayer(
        tiles="https://nwy-tiles-api.prod.newaydata.com/tiles/{z}/{x}/{y}.jpg?path=latest/base/latest",
        attr='OpenFlightMaps', name='OFM - Relief', max_zoom=14, min_zoom=6, overlay=False, control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://nwy-tiles-api.prod.newaydata.com/tiles/{z}/{x}/{y}.png?path=latest/aero/latest",
        attr='OFM Aero', name='OFM - Aéro', max_zoom=14, min_zoom=6, overlay=True, control=True, transparent=True
    ).add_to(m)
    
    if len(route_coords) > 1:
        folium.PolyLine(route_coords, color="#FF00FF", weight=5, opacity=0.9, dash_array="10").add_to(m)
        
    for i, pt in enumerate(st.session_state.route):
        couleur, icone = "blue", "map-marker"
        if i == 0: couleur, icone = "green", "plane-departure"
        elif i == len(route_coords) - 1: couleur, icone = "red", "plane-arrival"
            
        folium.Marker(
            location=[pt["lat"], pt["lon"]],
            popup=f"<b>{pt['nom']}</b>", tooltip=pt['nom'],
            icon=folium.Icon(color=couleur, icon=icone, prefix='fa')
        ).add_to(m)
        
    folium.LayerControl(collapsed=False).add_to(m)
    
    map_data = st_folium(m, width=1200, height=600, returned_objects=["last_clicked"])
    
    if map_data and map_data.get("last_clicked"):
        lat_clic = map_data["last_clicked"]["lat"]
        lon_clic = map_data["last_clicked"]["lng"]
        str_clic = f"{lat_clic}-{lon_clic}"
        
        if st.session_state.last_map_added != str_clic:
            with st.container(border=True):
                st.markdown("### ➕ Ajouter ce point à la route")
                st.write(f"📍 Coordonnées ciblées : Lat {lat_clic:.5f} / Lon {lon_clic:.5f}")
                
                c1, c2, c3 = st.columns([1, 2, 1])
                with c1:
                    nom_nouveau = st.text_input("Nom du repère (ex: SW, LIL...)", "WPT")
                with c2:
                    options_insert = []
                    for i in range(len(st.session_state.route) - 1):
                        pt_a = st.session_state.route[i]['nom']
                        pt_b = st.session_state.route[i+1]['nom']
                        options_insert.append(f"Branche {i+1} : Insérer entre {pt_a} et {pt_b}")
                    options_insert.append("À la fin de la route (Nouvelle arrivée)")
                    
                    choix_insert = st.selectbox("Position d'insertion", options_insert)
                with c3:
                    st.write("") 
                    st.write("")
                    if st.button("Valider l'ajout", use_container_width=True):
                        nouveau_pt = create_point(nom_nouveau, lat_clic, lon_clic)
                        if "À la fin" in choix_insert:
                            st.session_state.route.append(nouveau_pt)
                        else:
                            idx = options_insert.index(choix_insert) + 1
                            st.session_state.route.insert(idx, nouveau_pt)
                            
                        st.session_state.last_map_added = str_clic
                        st.rerun()

# ------------------------------------------
# ONGLET 3 : DEVIS DE CENTRAGE
# ------------------------------------------
with tab_centrage:
    st.subheader("Masses et chargement")
    if len(st.session_state.route) == 0:
        st.warning("Ajoutez des points à la route pour calculer le centrage.")
    else:
        st.info(f"Le carburant aux étapes intermédiaires est calculé automatiquement (Conso {CONSO_BASE_L_H} L/h + {int((MARGE_CONSO-1)*100)}%, soit {CONSO_EFFECTIVE_L_H:.1f} L/h).")
        
        resultats_centrage = []
        colonnes_centrage = st.columns(len(st.session_state.route))
        carb_restant_list = []

        for i, pt in enumerate(st.session_state.route):
            with colonnes_centrage[i]:
                st.markdown(f"**{pt['nom']}**")
                pax = st.number_input(f"Pilote + Pax (kg)", min_value=0.0, value=140.0, step=1.0, key=f"pax_{pt['id']}")
                bag = st.number_input(f"Bagages (kg)", min_value=0.0, max_value=35.0, value=0.0, step=1.0, key=f"bag_{pt['id']}")
                
                if i == 0:
                    carb_litres = st.number_input(f"Carburant Initial (L)", min_value=0.0, max_value=CAPACITE_MAX_CARBURANT_L, value=70.0, step=1.0, key=f"carb_init")
                    carb_restant_list.append(carb_litres)
                else:
                    temps_etape = temps_branches_min[i-1] if len(temps_branches_min) > i-1 else 0
                    conso_litres = (temps_etape / 60.0) * CONSO_EFFECTIVE_L_H
                    carb_litres = max(0.0, carb_restant_list[-1] - conso_litres)
                    carb_restant_list.append(carb_litres)
                    
                    st.text_input(f"Carburant calculé (L)", value=f"{carb_litres:.1f}", disabled=True, key=f"cauto_{pt['id']}_{carb_litres:.1f}")
                
                carb_kg = carb_litres * DENSITE_AVGAS
                masse, cg = calculer_centrage(avion_choisi, pax, bag, carb_kg)
                resultats_centrage.append({"Etape": pt['nom'], "Masse": masse, "CG": cg})

        st.markdown("---")
        col_graph, col_alertes = st.columns([2, 1])
        
        with col_graph:
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(ENVELOPPE_CG, ENVELOPPE_MASSE, 'r-', linewidth=2, label="Enveloppe autorisée")
            ax.fill(ENVELOPPE_CG, ENVELOPPE_MASSE, 'red', alpha=0.1)
            
            df_res_centrage = pd.DataFrame(resultats_centrage)
            colors = ['blue', 'purple', 'orange', 'green', 'brown', 'black']
            
            for i in range(len(df_res_centrage)):
                cg_actuel, masse_actuelle = df_res_centrage.loc[i, "CG"], df_res_centrage.loc[i, "Masse"]
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
                    st.error(f"⚠️ Centrage hors limites à : {row['Etape']}")
