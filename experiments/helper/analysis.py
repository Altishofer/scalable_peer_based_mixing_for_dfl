import numpy as np
import pandas as pd


def from_round_one(df):

    rounds = df[df["field"] == "current_round"]
    boot = rounds[rounds["value"] >= 1].groupby("node")["timestamp"].min().rename("boot_ts")

    merged = df.merge(boot, left_on="node", right_index=True, how="inner")

    return merged[merged["timestamp"] >= merged["boot_ts"]].drop(columns="boot_ts")


def cpu_seconds_per_round_per_node(df, n_rounds):
    out = []

    for node, df_node in df.groupby("node"):

        v = pd.to_numeric(df_node[df_node.field == "cpu_total_ns"].value, errors="coerce")
        v = v[v.notna()]

        out.append((v.max() - v.min()) * 10.0 / n_rounds)

    return out


def per_round_counter_delta(df, field, nodes, round_entry):

    all_rounds = sorted(int(c) for c in round_entry.columns)

    rounds = all_rounds[:-1]

    selected = df[(df.field == field) & (df.node.isin(nodes))].copy()
    selected["v"] = pd.to_numeric(selected.value, errors="coerce")
    selected = selected.dropna(subset=["v"]).sort_values(["node", "time_seconds"])

    final_out = np.full((len(nodes), len(rounds)), np.nan)

    node_idx = {n: i for i, n in enumerate(nodes)}

    for node, g in selected.groupby("node"):

        time_stamp = g.time_seconds.values
        values = g.v.values

        for round_index, round in enumerate(rounds):

            t_start = round_entry.at[node, round]

            if pd.isna(t_start):
                continue

            time_end = round_entry.at[node, all_rounds[round_index + 1]]

            if pd.isna(time_end):
                time_end = time_stamp[-1] + 1.0

            index_start = index_at_or_before(time_stamp, t_start)

            index_end = index_at_or_before(time_stamp, time_end)

            value_start = float(values[index_start]) if index_start >= 0 else 0.0
            value_end = float(values[index_end]) if index_end >= 0 else 0.0

            final_out[node_idx[node], round_index] = value_end - value_start

    return final_out, rounds


def keep_changes(series):
    return series != series.shift()


def index_at_or_before(sorted_ts, t):
    return np.searchsorted(sorted_ts, t, side="right") - 1


def align_to_rounds(left, right, on="timestamp", by="node"):
    return pd.merge_asof(
        left.sort_values(on),
        right.sort_values(on),
        on=on,
        by=by,
        direction="backward",
    )
