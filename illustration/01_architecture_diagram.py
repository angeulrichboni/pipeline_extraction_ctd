"""
Genere le diagramme d'architecture generale du pipeline (slide 3).
Sortie : 01_architecture_diagram.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(12, 7))
ax.set_xlim(0, 12)
ax.set_ylim(0, 7)
ax.axis("off")

phases = [
    ("A", "Preparation des donnees\net selection du corpus", "#4C72B0"),
    ("B", "Acquisition\ndocumentaire", "#55A868"),
    ("C", "Extraction structuree\npar agents specialises", "#C44E52"),
    ("D", "Assemblage, controle qualite\net enrichissement", "#8172B2"),
    ("E", "Dimensions complementaires\net fusion finale", "#CCB974"),
]

box_w, box_h = 2.0, 1.6
y = 3.5
xs = [0.7, 2.9, 5.1, 7.3, 9.5]

for (label, text, color), x in zip(phases, xs):
    box = FancyBboxPatch(
        (x, y - box_h / 2), box_w, box_h,
        boxstyle="round,pad=0.08,rounding_size=0.15",
        linewidth=1.5, edgecolor=color, facecolor=color, alpha=0.15,
    )
    ax.add_patch(box)
    ax.text(x + box_w / 2, y + box_h / 2 - 0.25, label,
             ha="center", va="center", fontsize=16, fontweight="bold", color=color)
    ax.text(x + box_w / 2, y - 0.15, text,
             ha="center", va="center", fontsize=9.5)

for x in xs[:-1]:
    arrow = FancyArrowPatch(
        (x + box_w, y), (x + box_w + 0.2, y),
        arrowstyle="-|>", mutation_scale=20, linewidth=1.5, color="black",
    )
    ax.add_patch(arrow)

ax.text(6, 6.3, "Pipeline d'extraction d'associations polluant-sante",
         ha="center", va="center", fontsize=15, fontweight="bold")
ax.text(6, 0.6,
        "CTD (referentiel polluants) -> PubMed/PMC (corpus) -> jeu de donnees structure et trace",
        ha="center", va="center", fontsize=10, style="italic", color="#444444")

plt.tight_layout()
plt.savefig("01_architecture_diagram.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 01_architecture_diagram.png")