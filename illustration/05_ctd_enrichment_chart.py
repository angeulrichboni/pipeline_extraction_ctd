"""
Genere le graphique des chiffres cles de l'enrichissement CTD (slide 10).
Sortie : 05_ctd_enrichment_chart.png

Valeurs actuelles = resultats reels du run PM (build_ctd_pm_enrichment).
"""
import matplotlib.pyplot as plt

categories = ["Genes humains\nlies disponibles", "Maladies\nmappees", "Phenotypes\nmappes"]
values = [8807, 76, 36]
totals = [8807, 421, 421]  # pour affichage "X / Y disponibles" sur genes/maladies/phenotypes
colors = ["#4C72B0", "#C44E52", "#8172B2"]

fig, ax = plt.subplots(figsize=(8, 6))
bars = ax.bar(categories, values, color=colors, alpha=0.85, width=0.55)

for bar, val, tot in zip(bars, values, totals):
    label = f"{val:,}".replace(",", " ")
    if tot != val:
        label += f"\n(sur {tot} candidats)"
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.02,
             label, ha="center", va="bottom", fontsize=10.5, fontweight="bold")

ax.set_ylabel("Nombre d'elements lies", fontsize=11)
ax.set_title("Enrichissement mecanistique CTD — branche PM", fontsize=13, fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
ax.set_yscale("symlog")  # les genes (8807) et maladies/phenotypes (dizaines) sont d'echelles tres differentes
ax.set_ylim(0, 15000)

plt.tight_layout()
plt.savefig("05_ctd_enrichment_chart.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 05_ctd_enrichment_chart.png")