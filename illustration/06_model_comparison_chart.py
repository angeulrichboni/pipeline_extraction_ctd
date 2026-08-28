"""
Genere le graphique de comparaison des modeles evalues (slide 12).
Sortie : 06_model_comparison_chart.png

Valeurs actuelles = scores de coherence mesures pendant la selection du
modele (agent pollutant, sauf mention contraire). Remplace par tes propres
chiffres si tu as retest sur un echantillon plus large.
"""
import matplotlib.pyplot as plt

models = ["qwen-3.6-35b-instruct", "gemma-4-31b", "mistral-small-4-119b"]
scores = [0.93, 0.75, 0.50]
retained = [True, False, False]

colors = ["#55A868" if r else "#C44E52" for r in retained]

fig, ax = plt.subplots(figsize=(9, 6))
bars = ax.barh(models, scores, color=colors, alpha=0.85, height=0.5)

for bar, score in zip(bars, scores):
    ax.text(bar.get_width() + 0.015, bar.get_y() + bar.get_height() / 2,
             f"{score:.2f}", va="center", fontsize=11, fontweight="bold")

ax.axvline(0.9, color="#888888", linestyle="--", linewidth=1)
ax.text(0.9, len(models) - 0.3, " seuil de stabilite (0.90)", fontsize=9, color="#555555", va="bottom")

ax.set_xlim(0, 1.05)
ax.set_xlabel("Score de coherence inter-executions", fontsize=11)
ax.set_title("Selection du modele de langage — critere de coherence", fontsize=13, fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
ax.invert_yaxis()

plt.tight_layout()
plt.savefig("06_model_comparison_chart.png", dpi=200, bbox_inches="tight")
print("Sauvegarde : 06_model_comparison_chart.png")