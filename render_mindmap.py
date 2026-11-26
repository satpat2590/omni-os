#!/usr/bin/env python3
"""Render the Omni mindmap as a static PNG + generate nodes JSON for interactivity.

Run after mindmap.py: python3 render_mindmap.py
"""

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT_DIR = Path(__file__).parent / "static"
GRAPH = OUT_DIR / "graph.json"
PNG = OUT_DIR / "mindmap.png"
NODES = OUT_DIR / "mindmap_nodes.json"

COLORS = {
    "atma": "#3fb950", "obsidian": "#58a6ff", "edoras-portfolio": "#d29922",
    "edoras-symbol": "#d29922", "whoop": "#f778ba", "cron": "#bc8cff",
}


def main():
    graph = json.loads(GRAPH.read_text())
    nodes = graph["nodes"]
    edges = graph["edges"]
    node_by_id = {n["id"]: n for n in nodes}

    # figure sized to data
    xs = [n["x"] for n in nodes]
    ys = [n["y"] for n in nodes]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
    figsize = max(10, min(20, span / 50))
    fig, ax = plt.subplots(figsize=(figsize, figsize), dpi=150)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    # edges
    for e in edges:
        a, b = node_by_id[e["source"]], node_by_id[e["target"]]
        ax.plot([a["x"], b["x"]], [a["y"], b["y"]],
                color="#58a6ff", alpha=0.06, linewidth=0.5, zorder=1)

    # nodes
    for n in nodes:
        pts = n.get("points") or 0
        color = COLORS.get(n["type"], "#8b949e")
        r = 2.5
        if n["type"] == "atma" and pts != 0:
            r = 3 + min(abs(pts) / 30, 5)
            color = "#f85149" if pts < 0 else ("#d29922" if pts < 10 else color)
        ax.scatter(n["x"], n["y"], s=r * 8, c=color, zorder=2, edgecolors="none")

    # labels (only for non-obsidian or high-points)
    for n in nodes:
        if n["type"] != "obsidian" or (n.get("points") or 0) > 20:
            ax.annotate(n["label"], (n["x"], n["y"]), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=6, color="#8b949e", zorder=3)

    ax.set_xlim(min(xs) - 20, max(xs) + 20)
    ax.set_ylim(min(ys) - 20, max(ys) + 20)
    ax.set_aspect("equal")
    ax.axis("off")
    plt.tight_layout(pad=0)
    fig.savefig(PNG, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0)
    plt.close()

    # interactive nodes JSON (positions normalized to 0-1 for CSS overlay)
    out = []
    for n in nodes:
        out.append({
            "id": n["id"], "label": n["label"], "type": n["type"],
            "category": n["category"], "points": n.get("points") or 0,
            "completions": n.get("completions", 0),
            "x": (n["x"] - min(xs)) / (max(xs) - min(xs)) if max(xs) > min(xs) else 0.5,
            "y": (n["y"] - min(ys)) / (max(ys) - min(ys)) if max(ys) > min(ys) else 0.5,
        })
    NODES.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {PNG} and {NODES}")


if __name__ == "__main__":
    main()
