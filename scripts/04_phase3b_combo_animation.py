# =============================================================================
#  phase3b_combo_animation.py   (white theme, manual geometry snapshot)
#  LinkedIn-ready 8-second combo MP4 (1920x1080, 30 fps).
#
#  Layout:
#    ┌──────────────────────────┬─────────────────────────┐
#    │                          │  Top: S11 (cursor)      │
#    │  3D rotating gain        ├─────────────────────────┤
#    │  pattern @ 2.45 GHz      │  Bottom: Phase-2 family │
#    │                          │                         │
#    │  Geometry snapshot       │                         │
#    │  (overlay, bottom-left)  │                         │
#    └──────────────────────────┴─────────────────────────┘
#
#  Reads:
#    csv/farfield_3d.npz        (theta_deg, phi_deg, gain_dBi)
#    csv/S11_dB.csv             (Freq_GHz, S11_dB)
#    csv/phase2_curves.npz      (patch_L_values, freqs_GHz, s11_dB_matrix)
#    csv/phase2_summary.json    (optimum L)
#    img/geometry_clean.png     (manual AEDT snapshot, AirBox hidden)
#
#  Writes:
#    img/patch_antenna_showcase.mp4
#
#  Notes:
#    - Gain corrected +3 dB at load time (half-symmetric model compensation).
#    - White theme for professional/LinkedIn appearance.
#    - 3D pattern is static at 2.45 GHz; only camera orbits.
#    - S11 cursor sweeps frequency to highlight resonance region.
# =============================================================================
from __future__ import annotations
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")

# --- FFmpeg path injection (Pattern 9) ---
try:
    import imageio_ffmpeg
    import os
    _ffpath = imageio_ffmpeg.get_ffmpeg_exe()
    if os.path.exists(_ffpath):
        matplotlib.rcParams["animation.ffmpeg_path"] = _ffpath
        print(f"  ✓ FFmpeg located: {_ffpath}")
except ImportError:
    print("  ⚠ imageio_ffmpeg not installed — MP4 will fail")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
from matplotlib.gridspec import GridSpec
from matplotlib.image import imread
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

warnings.filterwarnings("ignore", category=UserWarning)

# === CONFIG ==================================================================
PROJECT_DIR = Path(__file__).resolve().parent / "patch_showcase"
CSV_DIR     = PROJECT_DIR / "csv"
IMG_DIR     = PROJECT_DIR / "img"

DURATION_S  = 8.0
FPS         = 30
N_FRAMES    = int(DURATION_S * FPS)
DPI         = 120
FIGSIZE     = (16, 9)

GAIN_CORR_DB = 3.0
F0_GHZ       = 2.45

OUT_MP4 = IMG_DIR / "patch_antenna_showcase.mp4"
OUT_GIF = IMG_DIR / "patch_antenna_showcase.gif"

# --- WHITE THEME -------------------------------------------------------------
# (No plt.style.use() — it would reset rcParams including animation.ffmpeg_path)
ACCENT      = "#0066CC"   # professional blue
ACCENT2     = "#D4A017"   # warm gold (optimum)
ACCENT3     = "#CC2244"   # red (cursor)
GRID_C      = "#CCCCCC"
TEXT_C      = "#222222"
SUBTLE_C    = "#666666"
BG_C        = "#FFFFFF"
PANEL_BG    = "#FAFAFA"

# === LOADERS =================================================================
def load_farfield():
    p = CSV_DIR / "farfield_3d.npz"
    d = np.load(p)
    print(f"  farfield_3d.npz keys: {list(d.keys())}")
    theta = np.asarray(d["theta_deg"], dtype=float)
    phi   = np.asarray(d["phi_deg"],   dtype=float)
    gain  = np.asarray(d["gain_dBi"],  dtype=float) + GAIN_CORR_DB
    if np.isnan(gain).any():
        with np.errstate(all="ignore"):
            global_min = float(np.nanmin(gain))
            col_min = np.nanmin(gain, axis=0, keepdims=True)
        col_min = np.where(np.isnan(col_min), global_min, col_min)
        gain = np.where(np.isnan(gain), col_min, gain)
        print(f"  ℹ NaN cells filled (floor = {global_min:.2f} dBi)")
    return theta, phi, gain


def load_s11_csv():
    p = CSV_DIR / "S11_dB.csv"
    raw = np.genfromtxt(p, delimiter=",", names=True, dtype=float)
    if raw.dtype.names:
        f_key = next((n for n in raw.dtype.names if "freq" in n.lower() or n.lower().startswith("f")), raw.dtype.names[0])
        s_key = next((n for n in raw.dtype.names if "s11" in n.lower() or "db" in n.lower()), raw.dtype.names[1])
        f, s = raw[f_key].astype(float), raw[s_key].astype(float)
    else:
        arr = np.genfromtxt(p, delimiter=",", skip_header=1)
        f, s = arr[:, 0], arr[:, 1]
    if f.max() > 1e6:
        f = f / 1e9
    return f, s


def load_phase2_family():
    p = CSV_DIR / "phase2_curves.npz"
    d = np.load(p, allow_pickle=True)
    keys = list(d.keys())
    print(f"  phase2_curves.npz keys: {keys}")

    f_key = next((k for k in keys if "freq" in k.lower() or k.lower() in ("f", "f_ghz")), None)
    f = np.asarray(d[f_key], dtype=float)
    if f.max() > 1e6: f = f / 1e9

    L_key = next(
        (k for k in keys
         if any(tag in k.lower() for tag in ("l_value", "patch_l", "length", "l_mm"))
         and np.asarray(d[k]).ndim == 1),
        None,
    )
    L_vals = np.asarray(d[L_key], dtype=float) if L_key else None
    if L_key: print(f"  L-values key: '{L_key}' → {L_vals}")

    curve_arrays = []
    matrix_keys = [
        k for k in keys
        if np.asarray(d[k]).ndim == 2
        and any(tag in k.lower() for tag in ("s11", "matrix", "curves", "db"))
    ]
    if matrix_keys:
        M = np.asarray(d[matrix_keys[0]], dtype=float)
        print(f"  Matrix key: '{matrix_keys[0]}' shape={M.shape}")
        if M.shape[1] == len(f):
            for i in range(M.shape[0]): curve_arrays.append(M[i])
        elif M.shape[0] == len(f):
            for i in range(M.shape[1]): curve_arrays.append(M[:, i])
        else:
            raise ValueError(f"Matrix shape {M.shape} vs f len {len(f)}")
    if not curve_arrays:
        raise RuntimeError("No usable curve arrays")

    if L_vals is not None and len(L_vals) == len(curve_arrays):
        curves = [(f"L = {L_vals[i]:.1f} mm", curve_arrays[i], float(L_vals[i]))
                  for i in range(len(curve_arrays))]
    else:
        curves = [(f"Curve {i+1}", curve_arrays[i], float(i)) for i in range(len(curve_arrays))]

    opt_idx = 0
    summary_path = CSV_DIR / "phase2_summary.json"
    if summary_path.exists():
        try:
            summ = json.loads(summary_path.read_text())
            opt_L = float(summ.get("optimum_L_mm", summ.get("L_opt_mm", 28.4)))
            opt_idx = int(np.argmin([abs(c[2] - opt_L) for c in curves]))
            print(f"  Optimum L: {opt_L} mm → curve idx {opt_idx}")
        except Exception:
            opt_idx = int(np.argmin([np.min(c[1]) for c in curves]))
    return {"f_GHz": f, "curves": curves, "optimum": opt_idx}


def load_geometry_snapshot():
    """Loads img/geometry_clean.png — the manual AEDT snapshot."""
    p = IMG_DIR / "geometry_clean.png"
    if p.exists():
        print(f"  Geometry snapshot: {p.name}")
        return imread(p)
    print(f"  ⚠ {p.name} not found — geometry inset will be skipped")
    return None


# === 3D PATTERN ==============================================================
def build_pattern_surface(theta_deg, phi_deg, gain_dBi):
    THETA, PHI = np.meshgrid(theta_deg, phi_deg, indexing="ij")
    th, ph = np.deg2rad(THETA), np.deg2rad(PHI)
    floor_dB = max(np.nanmin(gain_dBi), np.nanmax(gain_dBi) - 25.0)
    g_clip = np.clip(gain_dBi, floor_dB, None)
    r = g_clip - floor_dB
    X = r * np.sin(th) * np.cos(ph)
    Y = r * np.sin(th) * np.sin(ph)
    Z = r * np.cos(th)
    return X, Y, Z, gain_dBi


# === FIGURE ==================================================================
def make_figure():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG_C)
    gs = GridSpec(
        2, 2, figure=fig,
        height_ratios=[1.0, 1.0],
        width_ratios=[1.05, 0.95],
        hspace=0.34, wspace=0.16,
        left=0.03, right=0.97, top=0.91, bottom=0.08,
    )
    ax_3d  = fig.add_subplot(gs[:, 0], projection="3d")
    ax_s11 = fig.add_subplot(gs[0, 1])
    ax_fam = fig.add_subplot(gs[1, 1])
    ax_3d.set_facecolor(BG_C)
    ax_s11.set_facecolor(PANEL_BG)
    ax_fam.set_facecolor(PANEL_BG)
    fig.suptitle(
        "ANSYS HFSS  ×  PyAEDT  —  2.45 GHz Inset-Fed Patch Antenna",
        fontsize=20, color=TEXT_C, weight="bold", y=0.965,
    )
    return fig, ax_3d, ax_s11, ax_fam


# === MAIN ====================================================================
def main():
    t0 = time.time()
    print("=" * 72)
    print(" PHASE 3b — LinkedIn Combo Animation (white theme, v2)")
    print("=" * 72)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] Loading data...")
    theta_deg, phi_deg, gain_dBi = load_farfield()
    f_s11, s11_dB                = load_s11_csv()
    family                       = load_phase2_family()
    geom_img                     = load_geometry_snapshot()

    peak = float(np.nanmax(gain_dBi))
    ip, jp = np.unravel_index(np.nanargmax(gain_dBi), gain_dBi.shape)
    print(f"  Peak: {peak:.2f} dBi at θ={theta_deg[ip]:.1f}° φ={phi_deg[jp]:.1f}°")
    print(f"  S11 min: {s11_dB.min():.2f} dB at f={f_s11[np.argmin(s11_dB)]:.4f} GHz")

    print("\n[2/5] Building 3D pattern surface...")
    X, Y, Z, G = build_pattern_surface(theta_deg, phi_deg, gain_dBi)
    R_max = max(float(np.max(np.abs(X))), float(np.max(np.abs(Y))), float(np.max(np.abs(Z))))

    print("\n[3/5] Composing figure layout...")
    fig, ax_3d, ax_s11, ax_fam = make_figure()

    # ---- 3D pattern (left, full height)
    ax_3d.plot_surface(
        X, Y, Z,
        facecolors=plt.cm.turbo((G - G.min()) / (G.max() - G.min() + 1e-9)),
        rstride=1, cstride=1, linewidth=0, antialiased=True, shade=False,
    )
    ax_3d.set_box_aspect([1, 1, 0.9])
    ax_3d.set_xlim(-R_max, R_max); ax_3d.set_ylim(-R_max, R_max); ax_3d.set_zlim(-R_max, R_max)
    ax_3d.set_axis_off()
    ax_3d.set_title(f"3D Gain Pattern @ {F0_GHZ} GHz   peak ≈ {peak:.1f} dBi",
                    color=ACCENT, fontsize=14, pad=-2, weight="bold")

    sm = plt.cm.ScalarMappable(cmap="turbo",
        norm=plt.Normalize(vmin=float(G.min()), vmax=float(G.max())))
    cbar = fig.colorbar(sm, ax=ax_3d, shrink=0.55, pad=-0.02, aspect=18)
    cbar.set_label("Gain (dBi)", color=TEXT_C, fontsize=10)
    cbar.ax.tick_params(colors=TEXT_C, labelsize=9)
    cbar.outline.set_edgecolor(GRID_C)

    # ---- S11 panel (top-right) with sweeping cursor
    ax_s11.plot(f_s11, s11_dB, color=ACCENT, lw=2.4, label="|S11|")
    ax_s11.axhline(-10, color=SUBTLE_C, ls="--", lw=1.0, alpha=0.7, label="−10 dB")
    below = s11_dB < -10
    if below.any():
        ax_s11.fill_between(f_s11, s11_dB, -10, where=below,
                            color=ACCENT, alpha=0.15, interpolate=True)
    ax_s11.set_xlim(f_s11.min(), f_s11.max())
    ax_s11.set_ylim(min(s11_dB.min() - 2, -32), 2)
    ax_s11.set_xlabel("Frequency (GHz)", color=TEXT_C, fontsize=10)
    ax_s11.set_ylabel("|S11| (dB)", color=TEXT_C, fontsize=10)
    ax_s11.set_title("Return Loss — Optimum Design",
                     color=ACCENT, fontsize=12, weight="bold")
    ax_s11.grid(True, color=GRID_C, alpha=0.7)
    ax_s11.tick_params(colors=TEXT_C, labelsize=9)
    for spine in ax_s11.spines.values(): spine.set_color(SUBTLE_C)
    ax_s11.legend(loc="lower right", facecolor="white", edgecolor=GRID_C,
                  labelcolor=TEXT_C, fontsize=9)

    # Animated cursor
    cursor_v   = ax_s11.axvline(f_s11[0], color=ACCENT3, lw=1.6, alpha=0.85)
    cursor_pt, = ax_s11.plot([f_s11[0]], [s11_dB[0]], "o",
                              color=ACCENT3, ms=9, mec="white", mew=1.2, zorder=6)
    cursor_txt = ax_s11.text(0.025, 0.07, "", transform=ax_s11.transAxes,
                              color=ACCENT3, fontsize=10, weight="bold",
                              bbox=dict(facecolor="white", edgecolor=ACCENT3,
                                        boxstyle="round,pad=0.3"))

    # ---- Family panel (bottom-right)
    cmap_fam = plt.cm.viridis(np.linspace(0.15, 0.85, len(family["curves"])))
    f_fam = family["f_GHz"]
    opt_idx = family["optimum"]
    for i, (label, curve, Lv) in enumerate(family["curves"]):
        is_opt = (i == opt_idx)
        ax_fam.plot(
            f_fam, curve,
            color=(ACCENT2 if is_opt else cmap_fam[i]),
            lw=(2.8 if is_opt else 1.4),
            alpha=(1.0 if is_opt else 0.85),
            label=(f"★ {label}" if is_opt else label),
            zorder=(5 if is_opt else 2),
        )
    ax_fam.axhline(-10, color=SUBTLE_C, ls="--", lw=1.0, alpha=0.6)
    ax_fam.axvline(F0_GHZ, color=SUBTLE_C, ls=":", lw=1.0, alpha=0.6)
    ax_fam.set_xlim(f_fam.min(), f_fam.max())
    ax_fam.set_ylim(min(min(c[1].min() for c in family["curves"]) - 2, -32), 2)
    ax_fam.set_xlabel("Frequency (GHz)", color=TEXT_C, fontsize=10)
    ax_fam.set_ylabel("|S11| (dB)", color=TEXT_C, fontsize=10)
    ax_fam.set_title("Phase-2 Parametric Sweep — Patch Length L",
                     color=ACCENT, fontsize=12, weight="bold")
    ax_fam.grid(True, color=GRID_C, alpha=0.7)
    ax_fam.tick_params(colors=TEXT_C, labelsize=9)
    for spine in ax_fam.spines.values(): spine.set_color(SUBTLE_C)
    ax_fam.legend(loc="lower right", facecolor="white", edgecolor=GRID_C,
                  labelcolor=TEXT_C, fontsize=8, ncol=2)

    # ---- Geometry inset (overlay on left panel, bottom-left corner)
    if geom_img is not None:
        ax_inset = fig.add_axes([0.025, 0.05, 0.26, 0.30])
        ax_inset.imshow(geom_img)
        ax_inset.set_xticks([]); ax_inset.set_yticks([])
        for spine in ax_inset.spines.values():
            spine.set_color(ACCENT); spine.set_linewidth(1.5)
        ax_inset.set_title("Geometry", color=ACCENT, fontsize=10, pad=3, weight="bold")

    # Footnote
    fig.text(0.5, 0.018,
             "Half-symmetric HFSS model • +3 dB gain compensation (wedge-model standard) • "
             "Driven Modal • FR4 εr=4.4 • Inset-fed microstrip",
             ha="center", color=SUBTLE_C, fontsize=9, style="italic")

    # === ANIMATION ===========================================================
    azim_start, azim_end = 30.0, 30.0 + 360.0
    elev_start, elev_end = 25.0, 35.0
    f_lo, f_hi = f_s11.min(), f_s11.max()

    # Cursor sweeps a meaningful range — focus on the resonance neighborhood,
    # not the whole 2-3 GHz band (otherwise it spends most time in flat regions)
    f_cursor_lo = max(f_lo, F0_GHZ - 0.20)
    f_cursor_hi = min(f_hi, F0_GHZ + 0.20)

    def update(frame):
        u = frame / max(N_FRAMES - 1, 1)
        # 3D camera orbit
        ax_3d.view_init(elev=elev_start + (elev_end - elev_start) * u,
                        azim=azim_start + (azim_end - azim_start) * u)
        # S11 cursor — ping-pong over resonance band for visual interest
        # u_cursor: 0->1->0 (triangle wave) so it sweeps in then back out
        u_cur = 1.0 - abs(2.0 * u - 1.0)
        f_cur = f_cursor_lo + (f_cursor_hi - f_cursor_lo) * u_cur
        k = int(np.argmin(np.abs(f_s11 - f_cur)))
        s_cur = float(s11_dB[k])
        cursor_v.set_xdata([f_s11[k], f_s11[k]])
        cursor_pt.set_data([f_s11[k]], [s_cur])
        cursor_txt.set_text(f"f = {f_s11[k]:.3f} GHz\n|S11| = {s_cur:.2f} dB")
        return cursor_v, cursor_pt, cursor_txt

    print(f"\n[4/5] Rendering {N_FRAMES} frames @ {FPS} fps...")
    anim = FuncAnimation(fig, update, frames=N_FRAMES, interval=1000.0/FPS, blit=False)

    wrote_path = None
    try:
        # Re-arm FFmpeg path defensively — some matplotlib operations
        # (e.g. plt.style.use, certain backend switches) silently reset
        # animation.ffmpeg_path back to default.
        try:
            import imageio_ffmpeg
            _ff_now = imageio_ffmpeg.get_ffmpeg_exe()
            matplotlib.rcParams["animation.ffmpeg_path"] = _ff_now
            print(f"  [FFmpeg re-armed] {_ff_now}")
            print(f"  [FFmpeg verify ] rcParams = "
                  f"{matplotlib.rcParams['animation.ffmpeg_path']}")
        except Exception as _e:
            print(f"  ⚠ FFmpeg re-arm failed: {_e}")

        writer = FFMpegWriter(
            fps=FPS, codec="libx264", bitrate=8000,
            extra_args=["-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18"],
        )
        print(f"  Encoding MP4 → {OUT_MP4.name} ...")
        anim.save(
            str(OUT_MP4), writer=writer, dpi=DPI,
            savefig_kwargs={"facecolor": fig.get_facecolor()},
            progress_callback=lambda i, n: print(f"    frame {i+1}/{n}", end="\r")
            if (i + 1) % 10 == 0 or i == n - 1 else None,
        )
        wrote_path = OUT_MP4
        print(f"\n  ✓ MP4 written: {OUT_MP4}")
    except Exception as e:
        print(f"\n  ⚠ MP4 failed: {e}")
        try:
            print("    (downscaling for GIF fallback...)")
            writer = PillowWriter(fps=15)
            anim.save(str(OUT_GIF), writer=writer, dpi=60,
                      savefig_kwargs={"facecolor": fig.get_facecolor()})
            wrote_path = OUT_GIF
            print(f"  ✓ GIF written: {OUT_GIF}")
        except Exception as e2:
            print(f"  ❌ GIF also failed: {e2}")

    plt.close(fig)

    print(f"\n[5/5] Summary")
    if wrote_path:
        sz_mb = wrote_path.stat().st_size / (1024 * 1024)
        print(f"  Output: {wrote_path}")
        print(f"  Size:   {sz_mb:.2f} MB")
    print(f"  Total wall time: {(time.time() - t0):.1f} s")
    print(f"\n  ✅ Phase 3b complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)