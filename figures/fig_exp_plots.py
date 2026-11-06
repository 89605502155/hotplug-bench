# -*- coding: utf-8 -*-
"""Data figures for the experiments, black-and-white, TIFF 600 dpi, 170 mm wide.

fig5_exp1_dimm.tiff   DIMM hot-unplug completion by onlining policy (exp. 1)
fig6_exp2_frag.tiff   virtio-mem residual after shrink vs guest fragmentation
                      (exp. 2)
fig7_exp3_coop.tiff   memory the host gets back for three guest behaviours
                      (exp. 3)
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(os.path.dirname(HERE), "results")
OUT = os.path.join(os.path.dirname(HERE), "figures_out")
os.makedirs(OUT, exist_ok=True)

for p in ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
    if os.path.exists(p):
        font_manager.fontManager.addfont(p)
rcParams.update({
    "font.family": "Liberation Sans",
    "font.size": 8,
    "axes.linewidth": 0.6,
    "savefig.dpi": 600,
})
MM = 1 / 25.4
GREY = "0.55"
DARK = "0.15"


def fig_exp1():
    rows = json.load(open(os.path.join(RESULTS, "exp1_dimm_unplug.json")))
    policies = ["online", "online_movable"]
    labels = {"online": "online\n(обычная зона)",
              "online_movable": "online_movable\n(зона ZONE_MOVABLE)"}
    rates, times = [], []
    for pol in policies:
        trials = [r for r in rows if r["policy"] == pol]
        ok = [r for r in trials if r["unplug_completed"]]
        rates.append(100.0 * len(ok) / len(trials) if trials else 0)
        times.append(sum(r["unplug_s"] for r in ok) / len(ok) if ok else 0)

    fig, ax = plt.subplots(figsize=(110 * MM, 62 * MM))
    xs = range(len(policies))
    bars = ax.bar(xs, rates, width=0.52,
                  color=["0.80", "0.45"], edgecolor="black", linewidth=0.7)
    ax.set_ylabel("Доля успешных извлечений, %")
    ax.set_ylim(0, 108)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([labels[p] for p in policies])
    for i, (b, pol) in enumerate(zip(bars, policies)):
        n = len([r for r in rows if r["policy"] == pol])
        ok = len([r for r in rows if r["policy"] == pol and r["unplug_completed"]])
        txt = f"{ok}/{n}"
        if times[i] > 0:
            txt += f"\n≈{times[i]*1000:.0f} мс"
        ax.text(b.get_x() + b.get_width() / 2, rates[i] + 2, txt,
                ha="center", va="bottom", fontsize=7.5)
    ax.text(0, 6, "ядро: unmovable page,\nOffline failed;\nQEMU без тайм-аута",
            ha="center", va="bottom", fontsize=6.3, color=DARK)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    out = os.path.join(OUT, "fig5_exp1_dimm.tiff")
    fig.savefig(out, format="tiff", pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    return out


def _spread(vals):
    m = sum(vals) / len(vals)
    return m, m - min(vals), max(vals) - m


def fig_exp2():
    rows = json.load(open(os.path.join(RESULTS, "exp2_virtio_mem_frag.json")))
    levels = sorted({r["frag_k"] for r in rows})
    groups = [[r for r in rows if r["frag_k"] == k] for k in levels]
    x = [_spread([r["slab_kb"] / 1024 for r in g])[0] for g in groups]
    ys = [_spread([r["achieved_mb"] for r in g]) for g in groups]
    y = [m for m, _, _ in ys]
    fig, ax = plt.subplots(figsize=(110 * MM, 62 * MM))
    # Reference: growth of unmovable kernel memory over the idle guest.
    ax.plot([x[0], x[-1]], [y[0], y[0] + x[-1] - x[0]], "--", color=GREY,
            linewidth=0.9, label="прирост Slab относительно\nисходного состояния")
    ax.errorbar(x, y, yerr=[[lo for _, lo, _ in ys], [hi for _, _, hi in ys]],
                fmt="-o", color="black", markerfacecolor="0.4",
                markeredgecolor="black", markersize=5, linewidth=1.1,
                capsize=2.5, elinewidth=0.7, label="остаток (среднее, 3 прогона)")
    for i, (xi, yi) in enumerate(zip(x, y)):
        first = i == 0
        ax.annotate(f"{yi:.0f} МиБ", (xi, yi),
                    textcoords="offset points",
                    xytext=(8, -3) if first else (-6, 4),
                    ha="left" if first else "right", fontsize=6.3)
    ax.set_xlabel("Неперемещаемая память ядра в госте (Slab), МиБ")
    ax.set_ylabel("Остаток после запроса\nсжатия до 0, МиБ")
    ax.set_ylim(0, 128)
    ax.set_xlim(min(x) - 4, max(x) + 6)
    ax.axhline(128, color="black", linewidth=0.5, linestyle=":")
    ax.text(min(x) - 2, 122, "подключено 128 МиБ", fontsize=6.3, va="top")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.9), fontsize=6.3,
              frameon=False)
    ax.grid(True, color="0.88", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    out = os.path.join(OUT, "fig6_exp2_frag.tiff")
    fig.savefig(out, format="tiff", pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    return out


def fig_exp3():
    rows = json.load(open(os.path.join(RESULTS, "exp3_uncooperative.json")))
    modes = ["cooperative", "no_driver", "busy"]
    labels = {"cooperative": "сговорчивый гость\n(память освобождена)",
              "no_driver": "драйвер virtio-mem\nне загружен",
              "busy": "память занята\nпроцессом гостя"}
    series = [
        ("подключено гостем, МиБ", lambda r: r["grown_mb"], "white", ""),
        ("прирост RSS QEMU, МиБ", lambda r: r["rss_grown"] - r["rss_idle"],
         "0.75", ""),
        ("возвращено хосту, МиБ", lambda r: r["host_reclaimed_mb"],
         "0.35", ""),
        ("осталось подключено, МиБ", lambda r: r["achieved_size_mb"],
         "white", "////"),
    ]
    fig, ax = plt.subplots(figsize=(150 * MM, 66 * MM))
    w = 0.19
    for j, (name, fn, col, hatch) in enumerate(series):
        stats = [_spread([fn(r) for r in rows if r["mode"] == m]) for m in modes]
        xs = [i + (j - 1.5) * w for i in range(len(modes))]
        ax.bar(xs, [max(m, 0) for m, _, _ in stats], width=w, color=col,
               hatch=hatch, edgecolor="black", linewidth=0.6, label=name,
               yerr=[[lo for _, lo, _ in stats], [hi for _, _, hi in stats]],
               error_kw={"elinewidth": 0.6, "capsize": 1.8})
        for xi, (m, _, hi) in zip(xs, stats):
            ax.text(xi, max(m, 0) + hi + 2, f"{m:.0f}", ha="center",
                    va="bottom", fontsize=6.3)
    ax.set_xticks(range(len(modes)))
    ax.set_xticklabels([labels[m] for m in modes])
    ax.set_ylabel("Объём памяти, МиБ")
    ax.text(1, 14, "запрошено 128 МиБ,\nзапрос не исполнен,\nQEMU не сообщает\nоб ошибке",
            ha="center", va="bottom", fontsize=6.3, color=DARK)
    ax.set_ylim(0, 145)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=6.3,
              frameon=False, ncol=4,
              handlelength=1.6, columnspacing=1.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    out = os.path.join(OUT, "fig7_exp3_coop.tiff")
    fig.savefig(out, format="tiff", pil_kwargs={"compression": "tiff_lzw"})
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(fig_exp1())
    print(fig_exp2())
    print(fig_exp3())
