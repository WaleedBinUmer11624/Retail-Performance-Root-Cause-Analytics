"""Phase 8 figure: the prioritisation grid (evidence strength x financial relevance, decision category labelled).

One figure only: it shows at a glance why the largest amount (I1) is not an ACT NOW issue. Colour marks the
decision category, and every point also carries the category as text, so colour is never the only signal.
Palette: the first three categorical slots of the dataviz reference palette (validated all-pairs, light mode);
NO ACTION YET is a neutral grey outline.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COLOURS = {"INVESTIGATE FIRST": "#2a78d6", "MONITOR": "#eb6834", "ACT NOW": "#1baf7a", "NO ACTION YET": "#8f8d87"}
X = ["Low", "Medium", "High"]
Y = ["Not quantified", "Low", "Medium", "High"]
SHORT = {"I1": "Store cluster S03-S05", "I2": "E&T full-week stock-outs", "I3": "Voltix concentration",
         "I4": "E&T 'Faulty' returns", "I5": "H&K promotions", "I6": "E&T range / continuing SKUs",
         "I7": "Residual (not attributed)"}


def prioritisation_grid(prio, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for i in range(len(X) + 1):
        ax.axvline(i - 0.5, color=GRID, lw=1, zorder=0)
    for j in range(len(Y) + 1):
        ax.axhline(j - 0.5, color=GRID, lw=1, zorder=0)
    for r in prio.itertuples():
        x, y = X.index(r.evidence_strength), Y.index(r.financial_relevance)
        c = COLOURS[r.decision_category]
        filled = r.decision_category != "NO ACTION YET"
        ax.scatter([x - 0.36], [y], s=150, color=c if filled else SURFACE, edgecolor=c, linewidth=2, zorder=3)
        share = "" if r.share_of_decline != r.share_of_decline else f", {100 * r.share_of_decline:.0f}% of decline"
        if r.issue_id == "I3":
            share = f", {100 * r.share_of_decline:.0f}% (within I2)"
        ax.text(x - 0.28, y + 0.07, f"{r.issue_id} {SHORT[r.issue_id]}", fontsize=8.6, color=INK, va="center",
                fontweight="bold")
        ax.text(x - 0.28, y - 0.15, f"{r.decision_category}{share}", fontsize=8, color=INK2, va="center")
    ax.set_xlim(-0.5, len(X) - 0.5)
    ax.set_ylim(-0.5, len(Y) - 0.5)
    ax.set_xticks(range(len(X)), X, fontsize=9, color=INK2)
    ax.set_yticks(range(len(Y)), Y, fontsize=9, color=INK2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("Strength of causal evidence (Phase 6 evidence level)", fontsize=9.5, color=INK2, labelpad=8)
    ax.set_ylabel("Financial relevance (share of the H2 decline)", fontsize=9.5, color=INK2, labelpad=8)
    fig.suptitle("Size earns an investigation; only evidence earns ACT NOW", x=0.07, ha="left", fontsize=13, color=INK,
                 fontweight="bold", y=0.975)
    fig.text(0.07, 0.905, "The largest amount (I1) is investigated first because its cause is unknown. Only the mechanism\n"
             "with root-cause evidence (I2) gets operational controls now; other issues get evidence capture, governance "
             "and investigation.", fontsize=9, color=INK2,
             ha="left", linespacing=1.4)
    fig.text(0.07, 0.015, "Financial relevance: High >= 20%, Medium 5% to 20%, Low < 5% of the H2 change. Evidence: High = "
             "root-cause evidence, Medium = statistical association,\nLow = observed change or hypothesis. Colour repeats "
             "the category written under each issue. Source: reports/phase8/phase8_prioritisation_matrix.csv",
             fontsize=7.2, color=INK2, ha="left", linespacing=1.4)
    fig.subplots_adjust(left=0.13, right=0.97, top=0.84, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path
