"""
LEED v4 Scorecard Analysis — reproducible pipeline
===================================================

Reads the raw scorecard workbook, cleans it into a tidy table, computes the
summary statistics quoted in the README, and renders every chart in /assets.

Run from the repository root:

    pip install -r requirements.txt
    python analysis/leed_analysis.py

Author: Prasad Suryawanshi
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "SCORECA.xlsx"   # raw scorecards as transcribed from USGBC
PROCESSED = ROOT / "data" / "processed"
ASSETS = ROOT / "assets"

PROJECTS = {
    "Berlin sellersiebzehn":            {"short": "Berlin · sellersiebzehn"},
    "Graefelfing LifeScienceCenterLSC": {"short": "Gräfelfing · LSC"},
    "Hamburg Proebenweg":               {"short": "Hamburg · Proebenweg"},
    "Pineville Building801Replacement": {"short": "Pineville · Bldg 801"},
}
LEVEL_RANK = {"Certified": 1, "Silver": 2, "Gold": 3, "Platinum": 4}

CREDIT_LABELS = {
    "Optimize energy performance": "Optimize Energy Performance",
    "Enhanced commissioning": "Enhanced Commissioning",
    "Renewable energy production": "Renewable Energy Production",
    "Green power and carbon offsets": "Green Power & Carbon Offsets",
    "Demand response": "Demand Response",
    "Enhanced refrigerant Mgmt": "Enhanced Refrigerant Mgmt",
    "Advanced energy metering": "Advanced Energy Metering",
    "Building life-cycle impact reduction": "Whole-Building LCA (BLCIR)",
    "Building product disclosure and optimization - environmental product d": "EPDs",
    "Building product disclosure and optimization - sourcing of raw materia": "Raw-Material Sourcing",
    "Building product disclosure and optimization - sourcing of raw material": "Raw-Material Sourcing",
    "Building product disclosure and optimization - material ingredients": "Material Ingredients",
    "Construction and demolition waste Mgmt": "C&D Waste Management",
}

# Palette — light, print-friendly, colour-blind safe
INK, MUTED, GRID = "#1F2933", "#6B7785", "#E4E8EC"
GREEN, BLUE, AMBER = "#2E8B57", "#2F6DB5", "#D99A2B"
plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"],
    "font.size": 11,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK,
    "xtick.color": MUTED,
    "ytick.color": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.dpi": 200,
    "svg.fonttype": "none",
    "svg.hashsalt": "leed",
    "savefig.bbox": "tight",
})


# --------------------------------------------------------------------------- #
# 1. Clean
# --------------------------------------------------------------------------- #
def load_and_clean() -> pd.DataFrame:
    df = pd.read_excel(RAW, sheet_name="All_scorecards")
    df = df.rename(columns=str.strip)

    # Harmonise the three spellings of the MR category
    df["Category"] = np.where(
        df["Category"].str.contains("energy", case=False), "Energy & Atmosphere",
        "Materials & Resources",
    )

    # Keep scored credits only. The "Optimize Energy Performance (2024 Update)"
    # row is a v4.1 placeholder (0/20 for every project) and would distort the
    # achievement rates, so it is excluded.
    df = df[(df["type_cleaned"] == "Credit") & (df["Possible"] > 0)]
    df = df[~df["Name"].str.contains("2024 Update")]

    df["Credit"] = df["Name"].str.strip().map(CREDIT_LABELS)
    assert df["Credit"].notna().all(), "Unmapped credit name in raw data"

    df["Project"] = df["Building"].map(lambda b: PROJECTS[b]["short"])
    df["Achievement"] = df["Achieved"] / df["Possible"]

    tidy = df[["Project", "Country", "Level", "Category", "Credit",
               "Achieved", "Possible", "Achievement"]].reset_index(drop=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    tidy.to_csv(PROCESSED / "leed_credits_tidy.csv", index=False)
    return tidy


# --------------------------------------------------------------------------- #
# 2. Analyse
# --------------------------------------------------------------------------- #
def summarise(t: pd.DataFrame) -> dict:
    by_proj = (t.pivot_table(index=["Project", "Country", "Level"],
                             columns="Category", values=["Achieved", "Possible"],
                             aggfunc="sum"))
    by_proj.columns = [f"{a}_{'EA' if 'Energy' in c else 'MR'}" for a, c in by_proj.columns]
    by_proj = by_proj.reset_index()
    by_proj["LevelRank"] = by_proj["Level"].map(LEVEL_RANK)
    by_proj["EA_pct"] = by_proj["Achieved_EA"] / by_proj["Possible_EA"]
    by_proj["MR_pct"] = by_proj["Achieved_MR"] / by_proj["Possible_MR"]
    by_proj.to_csv(PROCESSED / "leed_project_summary.csv", index=False)

    credit = (t.groupby(["Category", "Credit"])
                .agg(Achieved=("Achieved", "sum"), Possible=("Possible", "sum"),
                     Projects_scoring=("Achieved", lambda s: int((s > 0).sum())))
                .reset_index())
    credit["Achievement"] = credit["Achieved"] / credit["Possible"]
    credit = credit.sort_values("Achievement", ascending=False)
    credit.to_csv(PROCESSED / "leed_credit_summary.csv", index=False)

    oep = t[t["Credit"] == "Optimize Energy Performance"]["Achieved"]
    de = by_proj[by_proj["Country"] == "Germany"]
    us = by_proj[by_proj["Country"] == "U.S."]
    stats = {
        "oep_mean": oep.mean(),
        "ea_mean_pct": by_proj["EA_pct"].mean(),
        "mr_mean_pct": by_proj["MR_pct"].mean(),
        "mr_de_pct": de["Achieved_MR"].sum() / de["Possible_MR"].sum(),
        "mr_us_pct": us["Achieved_MR"].sum() / us["Possible_MR"].sum(),
        "rho_ea_level": by_proj[["Achieved_EA", "LevelRank"]].corr("spearman").iloc[0, 1],
        "rho_mr_level": by_proj[["Achieved_MR", "LevelRank"]].corr("spearman").iloc[0, 1],
        "metering_scored": int(credit.loc[credit.Credit == "Advanced Energy Metering",
                                          "Projects_scoring"].iloc[0]),
    }
    return {"projects": by_proj, "credits": credit, "stats": stats}


# --------------------------------------------------------------------------- #
# 3. Visualise
# --------------------------------------------------------------------------- #
def chart_heatmap(t: pd.DataFrame, credit: pd.DataFrame) -> None:
    order_proj = [v["short"] for v in PROJECTS.values()]
    order_cred = list(credit.sort_values(["Category", "Achievement"],
                                         ascending=[True, False])["Credit"])
    pivot = t.pivot_table(index="Credit", columns="Project", values="Achievement")
    pivot = pivot.reindex(index=order_cred, columns=order_proj)
    label = t.assign(L=t["Achieved"].astype(int).astype(str) + "/" + t["Possible"].astype(int).astype(str)) \
             .pivot_table(index="Credit", columns="Project", values="L", aggfunc="first") \
             .reindex(index=order_cred, columns=order_proj)

    cmap = LinearSegmentedColormap.from_list("leed", ["#FBEDEA", "#F6F1E4", "#CFE8D8", GREEN])
    fig, ax = plt.subplots(figsize=(10, 6.6))
    ax.imshow(pivot.values, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.iat[i, j]
            ax.text(j, i, label.iat[i, j] if isinstance(label.iat[i, j], str) else "–",
                    ha="center", va="center", fontsize=10.5,
                    color="white" if v >= 0.8 else INK, fontweight="semibold")
    ax.set_xticks(range(len(order_proj)), [p.replace(" · ", "\n") for p in order_proj])
    ax.set_yticks(range(len(order_cred)), order_cred)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    for s in ax.spines.values():
        s.set_visible(False)
    n_ea = (credit["Category"] == "Energy & Atmosphere").sum()
    ax.axhline(n_ea - 0.5, color=INK, lw=1.2)
    ax.set_title("Credit achievement by project — LEED v4 BD+C\n", loc="left",
                 fontsize=14, fontweight="bold", color=INK)
    fig.text(0.0, -0.02, "Cells show points achieved / possible. Colour = achievement rate. "
             "Energy & Atmosphere above the rule, Materials & Resources below. – = not scored.",
             fontsize=9, color=MUTED, transform=ax.transAxes)
    fig.savefig(ASSETS / "credit_heatmap.svg")
    plt.close(fig)


def chart_credit_gap(credit: pd.DataFrame) -> None:
    c = credit.sort_values("Achievement")
    colors = [GREEN if cat == "Energy & Atmosphere" else BLUE for cat in c["Category"]]
    fig, ax = plt.subplots(figsize=(9, 5.8))
    ax.barh(c["Credit"], c["Achievement"] * 100, color=colors, height=0.62)
    for y, (v, a, p) in enumerate(zip(c["Achievement"], c["Achieved"], c["Possible"])):
        ax.text(v * 100 + 1.5, y, f"{v:.0%}  ({int(a)}/{int(p)} pts)", va="center",
                fontsize=9.5, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_title("Where the points are — and where they are left on the table",
                 loc="left", fontsize=14, fontweight="bold", color=INK, pad=24)
    ax.text(0, 1.02, "Share of available points captured across all four projects",
            transform=ax.transAxes, fontsize=10, color=MUTED)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=GREEN),
                       plt.Rectangle((0, 0), 1, 1, color=BLUE)],
              labels=["Energy & Atmosphere", "Materials & Resources"],
              loc="lower right", frameon=False, fontsize=9.5)
    fig.savefig(ASSETS / "credit_gap_ranking.svg")
    plt.close(fig)


def chart_projects(p: pd.DataFrame) -> None:
    p = p.sort_values(["LevelRank", "Achieved_EA"], ascending=True)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    y = np.arange(len(p))
    ax.barh(y + 0.19, p["EA_pct"] * 100, height=0.36, color=GREEN, label="Energy & Atmosphere")
    ax.barh(y - 0.19, p["MR_pct"] * 100, height=0.36, color=BLUE, label="Materials & Resources")
    for i, r in enumerate(p.itertuples()):
        ax.text(r.EA_pct * 100 + 1.2, i + 0.19, f"{int(r.Achieved_EA)}/{int(r.Possible_EA)}",
                va="center", fontsize=9, color=INK)
        ax.text(r.MR_pct * 100 + 1.2, i - 0.19, f"{int(r.Achieved_MR)}/{int(r.Possible_MR)}",
                va="center", fontsize=9, color=INK)
    ax.set_yticks(y, [f"{r.Project}\n{r.Level} · {r.Country}" for r in p.itertuples()],
                  fontsize=9.5)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="lower right", frameon=False, fontsize=9, ncol=2, bbox_to_anchor=(1, -0.32))
    ax.set_title("EA vs MR achievement rate per project", loc="left",
                 fontsize=14, fontweight="bold", color=INK, pad=12)
    fig.savefig(ASSETS / "project_ea_mr.svg")
    plt.close(fig)


def main() -> None:
    tidy = load_and_clean()
    res = summarise(tidy)
    ASSETS.mkdir(exist_ok=True)
    chart_heatmap(tidy, res["credits"])
    chart_credit_gap(res["credits"])
    chart_projects(res["projects"])

    s = res["stats"]
    print("\nKEY STATISTICS")
    print(f"  Optimize Energy Performance, mean points ......... {s['oep_mean']:.1f} / 18")
    print(f"  EA achievement rate, project mean ................ {s['ea_mean_pct']:.0%}")
    print(f"  MR achievement rate, project mean ................ {s['mr_mean_pct']:.0%}")
    print(f"  MR achievement — Germany vs U.S. ................. {s['mr_de_pct']:.0%} vs {s['mr_us_pct']:.0%}")
    print(f"  Spearman ρ  EA points ~ certification level ...... {s['rho_ea_level']:.2f}")
    print(f"  Spearman ρ  MR points ~ certification level ...... {s['rho_mr_level']:.2f}")
    print(f"  Projects scoring Advanced Energy Metering ........ {s['metering_scored']} / 4")
    print("\nPROJECTS\n", res["projects"][["Project", "Level", "Achieved_EA",
                                         "Possible_EA", "Achieved_MR", "Possible_MR"]].to_string(index=False))
    print("\nCREDITS\n", res["credits"].to_string(index=False))


if __name__ == "__main__":
    main()
