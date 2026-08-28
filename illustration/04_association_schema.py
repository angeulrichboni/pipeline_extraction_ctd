"""
Genere le schema d'assemblage d'une association a partir des 3 agents (slide 9).
Sortie : 04_association_schema.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(10, 5.5))
ax.set_xlim(0, 10)
ax.set_ylim(0, 5.5)
ax.axis("off")

agents = [
    ("Pollutant Extractor", "NO2", "#4C72B0", 4.3),
    ("Outcome Extractor", "asthma", "#55A868", 2.7),
    ("Effect Measure Extractor", "OR = 1.12\n[1.07-1.17]", "#C44E52", 1.1),
]

box_w, box_h = 3.0, 1.15
for name, example, color, y in agents:
    box = FancyBboxPatch(
        (0.3, y - box_h / 2), box_w, box_h, boxstyle="round,pad=0.08,rounding_size=0.12",
        linewidth=1.5, edgecolor=color, facecolor=color, alpha=0.15,
    )
    ax.add_patch(box)
    ax.text(0.3 + box_w / 2, y + 0.22, name, ha="center", va="center", fontsize=10, fontweight="bold")
    ax.text(0.3 + box_w / 2, y - 0.22, example, ha="center", va="center", fontsize=9.5, color="#333333")

    arrow = FancyArrowPatch(
        (0.3 + box_w, y), (6.1, 2.7),
        arrowstyle="-|>", mutation_scale=16, linewidth=1.2, color="#888888",
        connectionstyle=f"arc3,rad={(y - 2.7) * 0.15}",
    )
    ax.add_patch(arrow)

# Association finale
assoc_box = FancyBboxPatch(
    (6.3, 1.6), 3.2, 2.2, boxstyle="round,pad=0.1,rounding_size=0.15",
    linewidth=2, edgecolor="#8172B2", facecolor="#8172B2", alpha=0.15,
)
ax.add_patch(assoc_box)
ax.text(7.9, 3.4, "Association", ha="center", va="center", fontsize=11, fontweight="bold")
ax.text(7.9, 2.55, "NO2 -> asthma\nOR = 1.12 [1.07-1.17]\nAssemblage deterministe",
         ha="center", va="center", fontsize=9.5)

ax.text(5, 5.1, "Assemblage d'une association a partir des 3 agents d'extraction",
         ha="center", va="center", fontsize=13, fontweight="bold")

plt.tight_layout()
plt.savefig("04_association_schema.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 04_association_schema.png")