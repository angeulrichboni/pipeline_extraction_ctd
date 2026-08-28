"""
Genere le graphique de couverture texte integral / resume seul (slide 5).
Sortie : 02_fulltext_chart.png

Remplace les valeurs ci-dessous par tes vrais chiffres si besoin
(valeurs actuelles : run PM, 432 articles).
"""
import matplotlib.pyplot as plt

TOTAL = 432
FULL_TEXT = 292
ABSTRACT_ONLY = 140

fig, ax = plt.subplots(figsize=(7, 7))

sizes = [FULL_TEXT, ABSTRACT_ONLY]
labels = [f"Texte integral\n{FULL_TEXT} articles ({FULL_TEXT/TOTAL:.0%})",
          f"Resume seul\n{ABSTRACT_ONLY} articles ({ABSTRACT_ONLY/TOTAL:.0%})"]
colors = ["#4C72B0", "#CCB974"]

wedges, texts = ax.pie(
    sizes, colors=colors, startangle=90,
    wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
)

for w, label in zip(wedges, labels):
    angle = (w.theta2 + w.theta1) / 2
    x = 1.25 * (angle < 180 or angle > 360) * 0 + 1.3 * __import__("math").cos(__import__("math").radians(angle))
    y = 1.3 * __import__("math").sin(__import__("math").radians(angle))
    ax.text(x, y, label, ha="center", va="center", fontsize=11)

ax.text(0, 0, f"{TOTAL}\narticles", ha="center", va="center", fontsize=16, fontweight="bold")
ax.set_title("Couverture documentaire du corpus (branche PM)", fontsize=13, fontweight="bold", pad=20)

plt.tight_layout()
plt.savefig("02_fulltext_chart.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 02_fulltext_chart.png")