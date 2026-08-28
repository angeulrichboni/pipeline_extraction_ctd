"""
Genere l'entonnoir des volumes produits a chaque etape (slide 13).
Sortie : 07_results_funnel.png

Valeurs actuelles = resultats reels du run complet, branche PM.
"""
import matplotlib.pyplot as plt

stages = [
    "Articles traites",
    "Mentions de polluants",
    "Outcomes de sante",
    "Mesures d'effet",
    "Associations construites",
    "Associations finales\n(apres QC + enrichissement)",
]
values = [432, 2378, 2182, 3441, 3003, 1875]
colors = plt.cm.Blues([0.9, 0.75, 0.65, 0.55, 0.45, 0.35])

fig, ax = plt.subplots(figsize=(9, 6.5))
bars = ax.barh(stages, values, color=colors, height=0.6)

for bar, val in zip(bars, values):
    ax.text(bar.get_width() + max(values) * 0.015, bar.get_y() + bar.get_height() / 2,
             f"{val:,}".replace(",", " "), va="center", fontsize=11, fontweight="bold")

ax.set_xlabel("Nombre d'enregistrements", fontsize=11)
ax.set_title("Volumes produits — pipeline complet (branche PM, 432 articles)",
              fontsize=12.5, fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
ax.invert_yaxis()
ax.set_xlim(0, max(values) * 1.15)

plt.tight_layout()
plt.savefig("07_results_funnel.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 07_results_funnel.png")