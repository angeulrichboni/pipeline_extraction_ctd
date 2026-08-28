"""
Genere le schema de segmentation d'un article en unites de traitement (slide 6).
Sortie : 03_segmentation_schema.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(11, 5.5))
ax.set_xlim(0, 11)
ax.set_ylim(0, 5.5)
ax.axis("off")

# Article source
article_box = FancyBboxPatch(
    (0.4, 1.8), 1.8, 1.8, boxstyle="round,pad=0.08,rounding_size=0.12",
    linewidth=1.5, edgecolor="#4C72B0", facecolor="#4C72B0", alpha=0.15,
)
ax.add_patch(article_box)
ax.text(1.3, 2.7, "Article\n(texte integral\nou resume)", ha="center", va="center", fontsize=10)

# Fleche vers segmentation
arrow1 = FancyArrowPatch((2.2, 2.7), (2.9, 2.7), arrowstyle="-|>", mutation_scale=18, linewidth=1.5)
ax.add_patch(arrow1)

# Segments (exemple : 4 segments representatifs, avec "..." pour signifier plus)
segment_labels = ["Introduction", "Methodes", "Resultats", "..."]
seg_x0 = 3.1
seg_w, seg_h = 1.5, 0.85
for i, label in enumerate(segment_labels):
    y = 4.3 - i * 1.05
    box = FancyBboxPatch(
        (seg_x0, y - seg_h / 2), seg_w, seg_h, boxstyle="round,pad=0.06,rounding_size=0.1",
        linewidth=1.2, edgecolor="#55A868", facecolor="#55A868", alpha=0.15,
    )
    ax.add_patch(box)
    ax.text(seg_x0 + seg_w / 2, y, label, ha="center", va="center", fontsize=9.5)
    arrow = FancyArrowPatch(
        (seg_x0 + seg_w, y), (seg_x0 + seg_w + 0.6, 2.7),
        arrowstyle="-|>", mutation_scale=14, linewidth=1, color="#888888",
        connectionstyle="arc3,rad=0.15",
    )
    ax.add_patch(arrow)

# Traitement independant
proc_box = FancyBboxPatch(
    (6.2, 1.9), 1.9, 1.6, boxstyle="round,pad=0.08,rounding_size=0.12",
    linewidth=1.5, edgecolor="#C44E52", facecolor="#C44E52", alpha=0.15,
)
ax.add_patch(proc_box)
ax.text(7.15, 2.7, "Analyse\nindependante\nde chaque unite", ha="center", va="center", fontsize=9.5)

arrow2 = FancyArrowPatch((8.1, 2.7), (8.8, 2.7), arrowstyle="-|>", mutation_scale=18, linewidth=1.5)
ax.add_patch(arrow2)

# Fusion
fusion_box = FancyBboxPatch(
    (9.0, 1.9), 1.6, 1.6, boxstyle="round,pad=0.08,rounding_size=0.12",
    linewidth=1.5, edgecolor="#8172B2", facecolor="#8172B2", alpha=0.15,
)
ax.add_patch(fusion_box)
ax.text(9.8, 2.7, "Fusion des\nresultats\npar article", ha="center", va="center", fontsize=9.5)

ax.text(5.5, 5.15, "Segmentation d'un article en unites de traitement",
         ha="center", va="center", fontsize=13, fontweight="bold")

plt.tight_layout()
plt.savefig("03_segmentation_schema.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 03_segmentation_schema.png")