import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
import io
from datetime import datetime

# ==========================================
# 1. DONNÉES DES AVIONS & CARBURANT
# ==========================================
# Constantes Carburant
DENSITE_AVGAS = 0.72  # kg/L pour l'AVGAS 100 LL
CAPACITE_MAX_CARBURANT_L = 118.0  # Litres

# Enveloppe commune aux HR200-120
# Limites verticales à 0.22 et 0.46, fermée en bas à 500 kg
ENVELOPPE_CG = [0.22, 0.22, 0.32, 0.46, 0.46, 0.22]
ENVELOPPE_MASSE = [500, 580, 780, 780, 500, 500]

AIRCRAFT_DATA = {
    "D-EVTL": {
        "masse_vide": 557.58, 
        "bras_vide": 0.276,   
        "bras": {
            "pilote_pax": 0.45,
            "carburant": 1.1,
            "bagages": 1.2
        },
        "masse_max": 780,
    },
    "F-HNBB": {
        "masse_vide": 541.90, 
        "bras_vide": 0.261,  
        "bras": {
            "pilote_pax": 0.45,
            "carburant": 1.1,
            "bagages": 1.2
        },
        "masse_max": 780,
    }
}

# ==========================================
# 2. FONCTIONS DE CALCUL
# ==========================================
def calculer_centrage(avion, masse_pilotes, masse_bagages, masse_carburant):
    data = AIRCRAFT_DATA[avion]
    
    masse_totale = data["masse_vide"] + masse_pilotes + masse_bagages + masse_carburant
    
    moment_vide = data["masse_vide"] * data["bras_vide"]
    moment_pilotes = masse_pilotes * data["bras"]["pilote_pax"]
    moment_bagages = masse_bagages * data["bras"]["bagages"]
    moment_carburant = masse_carburant * data["bras"]["carburant"]
    
    moment_total = moment_vide + moment_pilotes + moment_bagages + moment_carburant
    
    cg = moment_total / masse_totale if masse_totale > 0 else 0
    return masse_totale, cg

# ==========================================
# 3. INTERFACE STREAMLIT
# ==========================================
st.set_page_config(page_title="Prépa Nav VFR - HR200", layout="wide")
st.title("Calcul de Centrage - HR200-120")

# --- CHOIX DE L'AVION ---
avion_choisi = st.sidebar.selectbox("Sélectionnez l'avion", list(AIRCRAFT_DATA.keys()))
st.sidebar.markdown("---")

# --- CHOIX DU MODE ---
mode = st.sidebar.radio("Mode de vol", ["Local", "Navigation"])

# Configuration des points de vol
points_vol = []

if mode == "Local":
    st.header("Mode Local (Départ = Arrivée)")
    dep = st.text_input("Aérodrome (Code OACI)", "LFQQ")
    points_vol = [{"nom": f"Départ ({dep})"}, {"nom": f"Arrivée ({dep})"}]

else:
    st.header("Mode Navigation")
    col1, col2, col3 = st.columns(3)
    with col1:
        dep = st.text_input("Départ (OACI)", "LFQQ")
    with col2:
        nb_dest = st.number_input("Nombre de destinations intermédiaires", min_value=1, max_value=5, value=1)
    with col3:
        arr = st.text_input("Arrivée (OACI)", "LFQQ")
    
    points_vol.append({"nom": f"Départ ({dep})"})
    for i in range(int(nb_dest)):
        dest = st.text_input(f"Destination {i+1} (OACI)", f"DEST{i+1}")
        points_vol.append({"nom": dest})
    points_vol.append({"nom": f"Arrivée ({arr})"})

st.markdown("---")
st.subheader("Masses et chargement à chaque étape")
st.info(f"Capacité max carburant : {CAPACITE_MAX_CARBURANT_L} L, Densité AVGAS 100 LL = {DENSITE_AVGAS} kg/L.")

# Récupération des masses pour chaque point
resultats = []
colonnes = st.columns(len(points_vol))

for i, point in enumerate(points_vol):
    with colonnes[i]:
        st.markdown(f"**{point['nom']}**")
        pax = st.number_input(f"Pilote + Passager(s) (kg)", min_value=0.0, value=140.0, step=1.0, key=f"pax_{i}")
        bag = st.number_input(f"Bagages (kg)", min_value=0.0, max_value=35.0, value=0.0, step=1.0, key=f"bag_{i}")
        
        # Saisie en Litres avec limite à 118 L
        carb_litres = st.number_input(f"Carburant (L)", min_value=0.0, max_value=CAPACITE_MAX_CARBURANT_L, value=70.0, step=1.0, key=f"carb_{i}")
        
        # Conversion L -> kg
        carb_kg = carb_litres * DENSITE_AVGAS
        
        masse, cg = calculer_centrage(avion_choisi, pax, bag, carb_kg)
        resultats.append({"Etape": point['nom'], "Masse": masse, "CG": cg, "Carb_L": carb_litres})

# ==========================================
# 4. GRAPHIQUE ET RÉSULTATS
# ==========================================
st.markdown("---")
st.subheader("Enveloppe de centrage")

fig, ax = plt.subplots(figsize=(10, 6))

# Tracé de l'enveloppe
ax.plot(ENVELOPPE_CG, ENVELOPPE_MASSE, 'r-', linewidth=2, label="Enveloppe autorisée")
ax.fill(ENVELOPPE_CG, ENVELOPPE_MASSE, 'red', alpha=0.1)

# Tracé des points et des flèches chronologiques
df_res = pd.DataFrame(resultats)
colors = ['blue', 'purple', 'orange', 'green', 'brown', 'black']

for i in range(len(df_res)):
    cg_actuel = df_res.loc[i, "CG"]
    masse_actuelle = df_res.loc[i, "Masse"]
    etape_nom = df_res.loc[i, "Etape"]
    couleur = colors[i % len(colors)]
    
    # Tracer le point
    ax.plot(cg_actuel, masse_actuelle, marker='o', markersize=8, color=couleur)
    
    # Légender le point
    ax.text(cg_actuel + 0.002, masse_actuelle + 5, etape_nom, fontsize=10, color=couleur, fontweight='bold')
    
    # Tracer la flèche vers le point suivant
    if i < len(df_res) - 1:
        cg_suivant = df_res.loc[i+1, "CG"]
        masse_suivante = df_res.loc[i+1, "Masse"]
        
        ax.annotate('', 
                    xy=(cg_suivant, masse_suivante), 
                    xytext=(cg_actuel, masse_actuelle),
                    arrowprops=dict(arrowstyle="->", color='gray', lw=1.5, ls='--'))

# Ajustement de la fenêtre d'affichage du graphique
ax.set_xlim(0.18, 0.50)
ax.set_ylim(480, 800)

# Horodatage et immatriculation sur le graphique
date_actuelle = datetime.now().strftime("%d/%m/%Y à %H:%M")
titre_graphique = f"Évolution du centrage - {avion_choisi}"
ax.set_title(titre_graphique, fontsize=14, fontweight='bold', pad=15)
ax.text(0.02, 0.95, f"Généré le : {date_actuelle}", transform=ax.transAxes, fontsize=10, 
        verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

ax.set_xlabel("Centrage (m)")
ax.set_ylabel("Masse (kg)")
ax.grid(True, linestyle=':', alpha=0.7)
ax.legend(loc="upper right")

# Affichage dans Streamlit
col_graph, col_tableau = st.columns([2, 1])

with col_graph:
    st.pyplot(fig)
    
    # --- BOUTON DE TÉLÉCHARGEMENT ---
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=300)
    
    st.download_button(
        label="Télécharger le graphique (PNG)",
        data=buf.getvalue(),
        file_name=f"Centrage_{avion_choisi}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
        mime="image/png"
    )

with col_tableau:
    # On ajoute la colonne des litres dans l'affichage final pour vérification
    st.dataframe(df_res[["Etape", "Masse", "CG", "Carb_L"]].style.format({
        "Masse": "{:.1f} kg", 
        "CG": "{:.3f} m",
        "Carb_L": "{:.1f} L"
    }))

    # Vérifications et alertes de sécurité
    for i, row in df_res.iterrows():
        masse = row["Masse"]
        cg = row["CG"]
        
        if masse > AIRCRAFT_DATA[avion_choisi]["masse_max"]:
            st.error(f"⚠️ Dépassement masse max à : {row['Etape']}")
            
        if cg < 0.22:
            st.error(f"⚠️ Centrage trop AVANT à : {row['Etape']}")
        elif cg > 0.46:
            st.error(f"⚠️ Centrage trop ARRIÈRE à : {row['Etape']}")
        
        if 0.22 <= cg < 0.32:
            masse_max_locale = 2000 * (cg - 0.22) + 580
            if masse > masse_max_locale:
                st.error(f"⚠️ Dépassement de l'enveloppe avant/haut à : {row['Etape']}")
