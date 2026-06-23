import ast
import pathlib

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.style.use("default")
plt.rcParams.update(
    {
        "font.family": ["Liberation Sans", "DejaVu Sans"],
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.titlesize": 10,
        "axes.axisbelow": True,
        "axes.linewidth": 0.6,
        "axes.labelpad": 3.0,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.minor.visible": False,
        "ytick.minor.visible": False,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": False,
        "ytick.right": False,
        "lines.linewidth": 1.2,
        "patch.linewidth": 0.6,
        "legend.frameon": True,
        "legend.framealpha": 0.9,
        "legend.borderpad": 0.3,
        "legend.handlelength": 1.6,
        "legend.handletextpad": 0.5,
        "legend.columnspacing": 1.2,
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
        "savefig.edgecolor": "none",
        "savefig.transparent": True,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "standard",
        "savefig.dpi": 300,
        "savefig.pad_inches": 0.0,
    }
)

_TEXTWIDTH_IN = 160.0 / 25.4
_HALF_W = (_TEXTWIDTH_IN - 0.10) / 2

FIGURE_SIZE = (_TEXTWIDTH_IN, 0.40 * _TEXTWIDTH_IN)
FIGURE_SIZE_HALF = (_HALF_W, 0.75 * _HALF_W)

LINE_STYLE = {
    "linewidth": 1.2,
    "linestyle": "-",
}

MARKER_STYLE = {
    "marker": "o",
    "markersize": 3,
    "markeredgecolor": "none",
}

GRID_STYLE = {
    "visible": True,
    "linestyle": "--",
    "linewidth": 0.4,
    "alpha": 0.5,
}

slate_teal = "#335C67"
deep_red = "#9E2A2B"
warm_orange = "#E09F3E"
plum = "#5F0F40"
tan = "#B8A68E"
sage = "#99A88C"

navy = "#1F3A5F"
bordeaux = "#7B1E2A"

mid_grey = "#888888"
dark_grey = "#444444"

dark_green = "#2E7D32"

cmap_bridge = "#5B3D6B"
cream = "#F4EFE7"

REFERENCE_LINE_STYLE = {
    "color": dark_green,
    "linewidth": 1.2,
    "linestyle": "--",
}

THEORY_LINE_STYLE = {
    "color": dark_green,
    "linewidth": 1.2,
    "linestyle": "-.",
}

EVENT_BOUNDARY_STYLE = {
    "color": mid_grey,
    "linewidth": 1.2,
    "linestyle": ":",
    "alpha": 0.6,
}


def load_file(path):

    df = pd.read_csv(path, comment="#")

    if "timestamp" in df.columns:

        time_stamp = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        bad_formatting = time_stamp.isna()

        if bad_formatting.any():

            time_stamp.loc[bad_formatting] = pd.to_datetime(
                df.loc[bad_formatting, "timestamp"].str.replace("Z", "+00:00"),
                utc=True,
                errors="coerce",
            )

        df = df.assign(timestamp=time_stamp).dropna(subset=["timestamp"])

    else:
        df["timestamp"] = pd.Timestamp.utcnow()

    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df


def read_config_from_csv(path):
    # I set first line of every run to hold config
    try:

        with open(path) as f:
            first_line = f.readline().strip()

        if not first_line.startswith("#"):
            return {}

        raw = first_line[1:]

        return ast.literal_eval(raw)

    except Exception:
        return {}


def save_figure(fig, path):

    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches=None, pad_inches=0)


def list_runs(experiment_dir):

    base = pathlib.Path(experiment_dir)
    if not base.is_dir():
        return []

    runs = []

    for run_dir in sorted(base.iterdir()):

        if not run_dir.is_dir() or run_dir.name.endswith("__partial"):
            continue

        csvs = sorted(run_dir.glob("*.csv"))

        if csvs:
            runs.append((run_dir.name, str(csvs[-1])))

    return runs
