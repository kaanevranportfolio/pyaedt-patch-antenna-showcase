# =============================================================================
#  phase3b_combo_animation.py
#  LinkedIn-ready 8-second combo MP4 (1920x1080, 30 fps, dark theme).
#
#  Layout (4 panels):
#    ┌─────────────────────────┬─────────────────────────┐
#    │ 3D rotating gain        │ S11 with sweeping       │
#    │ pattern (turbo cmap)    │ frequency cursor        │
#    ├─────────────────────────┴─────────────────────────┤
#    │ Phase-2 parametric family-of-curves               │
#    │ (viridis cmap, optimum highlighted with ★)        │
#    └───────────────────────────────────────────────────┘
#  Corner inset: small geometry thumbnail (top-left of bottom panel).
#
#  Reads:
#    csv/farfield_3d.npz        (theta_deg, phi_deg, gain_dBi[, peak_*])
#    csv/S11_dB.csv             (freq_GHz, S11_dB)
#    csv/phase2_curves.npz      (sweep family — defensive key detection)
#    csv/phase2_summary.json    (optimum L, fres, bandwidth)
#    img/geometry_isometric.png OR img/geometry_symmetric_fixed.png
#
#  Writes:
#    img/patch_antenna_showcase.mp4 (or .gif fallback)
#
#  Notes:
#    - Gain corrected +3 dB at load time (half-symmetric model compensation).
#    - Pure matplotlib + numpy, no AEDT dependency.
# =============================================================================
from __future__ import annotations
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")               # headless rendering

# --- FFmpeg path injection (matplotlib doesn't auto-discover imageio-ffmpeg) ---
# Per AEDT Python env: imageio-ffmpeg ships its own bundled binary.
# Must be set BEFORE any animation.save() call.
try:
    import imageio_ffmpeg
    import os
    _ffpath = imageio_ffmpeg.get_ffmpeg_exe()
    if os.path.exists(_ffpath):
        matplotlib.rcParams["animation.ffmpeg_path"] = _ffpath
        print(f"  ✓ FFmpeg located: {_ffpath}")
    else:
        print(f"  ⚠ imageio_ffmpeg returned non-existent path: {_ffpath}")
except ImportError:
    print("  ⚠ imageio_ffmpeg not installed — MP4 will fail, GIF fallback only")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
from matplotlib.gridspec import GridSpec
from matplotlib.image import imread
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers projection)

warnings.filterwarnings("ignore", category=UserWarning)

# === CONFIG ==================================================================
PROJECT_DIR = Path(__file__).resolve().parent / "patch_showcase"
CSV_DIR     = PROJECT_DIR / "csv"
IMG_DIR     = PROJECT_DIR / "img"

DURATION_S  = 8.0
FPS         = 30
N_FRAMES    = int(DURATION_S * FPS)            # 240
DPI         = 120                              # 1920×1080 at fig=(16,9)
FIGSIZE     = (16, 9)

GAIN_CORR_DB = 3.0                              # half-symmetric compensation
F0_GHZ       = 2.45

OUT_MP4 = IMG_DIR / "patch_antenna_showcase.mp4"
OUT_GIF = IMG_DIR / "patch_antenna_showcase.gif"

# Visual theme
plt.style.use("dark_background")
ACCENT  = "#00E0FF"      # cyan highlight
ACCENT2 = "#FFD400"      # gold highlight (optimum)
GRID_C  = "#3a3a3a"

# === LOADERS =================================================================

def load_farfield():
    """Returns (theta_deg, phi_deg, gain_dBi_corrected)."""
    p = CSV_DIR / "farfield_3d.npz"
    d = np.load(p)
    print(f"  farfield_3d.npz keys: {list(d.keys())}")
    theta = np.asarray(d["theta_deg"], dtype=float)
    phi   = np.asarray(d["phi_deg"],   dtype=float)
    gain  = np.asarray(d["gain_dBi"],  dtype=float)
    # Apply half-symmetry compensation (Option A, locked-in decision)
    gain = gain + GAIN_CORR_DB
    # Replace NaNs with column min (defensive — your earlier NPZ was clean,
    # this is just belt-and-suspenders)
    if np.isnan(gain).any():
        # Use global min for any all-NaN columns, else per-column nanmin
        with np.errstate(all="ignore"):
            global_min = float(np.nanmin(gain))
            col_min = np.nanmin(gain, axis=0, keepdims=True)
        col_min = np.where(np.isnan(col_min), global_min, col_min)
        gain = np.where(np.isnan(gain), col_min, gain)
        print(f"  ℹ NaN cells filled (global floor = {global_min:.2f} dBi)")
    return theta, phi, gain


def load_s11_csv():
    """Returns (freq_GHz, s11_dB) for the optimum design."""
    p = CSV_DIR / "S11_dB.csv"
    # Defensive: try common header / no-header layouts
    raw = np.genfromtxt(p, delimiter=",", names=True, dtype=float)
    if raw.dtype.names:
        names = [n.lower() for n in raw.dtype.names]
        # Find frequency column
        f_key = next((n for n in raw.dtype.names if "freq" in n.lower() or n.lower().startswith("f")), raw.dtype.names[0])
        s_key = next((n for n in raw.dtype.names if "s11" in n.lower() or "db" in n.lower()), raw.dtype.names[1])
        f = raw[f_key].astype(float)
        s = raw[s_key].astype(float)
    else:
        arr = np.genfromtxt(p, delimiter=",", skip_header=1)
        f, s = arr[:, 0], arr[:, 1]
    # If freq is in Hz, convert
    if f.max() > 1e6:
        f = f / 1e9
    return f, s


def load_phase2_family():
    """
    Returns dict with:
      f_GHz   (N,)
      curves  list of (label, s11_db_array, L_value_mm)
      optimum index (int) into curves
    Defensive — the previous chat used various conventions.
    """
    p = CSV_DIR / "phase2_curves.npz"
    d = np.load(p, allow_pickle=True)
    keys = list(d.keys())
    print(f"  phase2_curves.npz keys: {keys}")

    # Frequency axis
    f_key = next((k for k in keys if "freq" in k.lower() or k.lower() in ("f", "f_ghz")), None)
    if f_key is None:
        raise KeyError(f"No frequency-like key in {keys}")
    f = np.asarray(d[f_key], dtype=float)
    if f.max() > 1e6:
        f = f / 1e9

    # L values — substring match on any key containing 'l_value', 'patch_l', 'length', or just 'l_'
    L_key = next(
        (k for k in keys
         if any(tag in k.lower() for tag in ("l_value", "patch_l", "length", "l_mm"))
         and np.asarray(d[k]).ndim == 1),
        None,
    )
    L_vals = np.asarray(d[L_key], dtype=float) if L_key else None
    if L_key:
        print(f"  L-values key: '{L_key}' → {L_vals}")

    # Curves — any 2D array whose name suggests S11 (matrix, db, s11, curves)
    curve_arrays = []
    matrix_keys = [
        k for k in keys
        if np.asarray(d[k]).ndim == 2
        and any(tag in k.lower() for tag in ("s11", "matrix", "curves", "db"))
    ]
    if matrix_keys:
        print(f"  Matrix key: '{matrix_keys[0]}' shape={np.asarray(d[matrix_keys[0]]).shape}")
    if matrix_keys:
        M = np.asarray(d[matrix_keys[0]], dtype=float)
        # Decide orientation: each curve along axis with length == len(f)
        if M.shape[1] == len(f):
            for i in range(M.shape[0]):
                curve_arrays.append(M[i])
        elif M.shape[0] == len(f):
            for i in range(M.shape[1]):
                curve_arrays.append(M[:, i])
        else:
            raise ValueError(f"Cannot orient matrix shape {M.shape} vs f len {len(f)}")
    else:
        # Try per-curve keys like s11_L27p8, etc.
        for k in keys:
            arr = np.asarray(d[k])
            if arr.ndim == 1 and len(arr) == len(f) and k != f_key and k != L_key:
                curve_arrays.append(arr.astype(float))

    if not curve_arrays:
        raise RuntimeError("No usable curve arrays found in phase2_curves.npz")

    # Build labelled list
    if L_vals is not None and len(L_vals) == len(curve_arrays):
        curves = [(f"L = {L_vals[i]:.1f} mm", curve_arrays[i], float(L_vals[i]))
                  for i in range(len(curve_arrays))]
    else:
        curves = [(f"Curve {i+1}", curve_arrays[i], float(i)) for i in range(len(curve_arrays))]

    # Optimum index — try summary JSON, else pick deepest min near F0
    opt_idx = 0
    summary_path = CSV_DIR / "phase2_summary.json"
    if summary_path.exists():
        try:
            summ = json.loads(summary_path.read_text())
            opt_L = float(summ.get("optimum_L_mm", summ.get("L_opt_mm", 28.4)))
            opt_idx = int(np.argmin([abs(c[2] - opt_L) for c in curves]))
            print(f"  Optimum L from summary: {opt_L} mm → curve idx {opt_idx}")
        except Exception as e:
            print(f"  ⚠ summary parse failed: {e}; auto-selecting optimum")
            opt_idx = int(np.argmin([np.min(c[1]) for c in curves]))
    else:
        opt_idx = int(np.argmin([np.min(c[1]) for c in curves]))

    return {"f_GHz": f, "curves": curves, "optimum": opt_idx}


def load_geometry_thumbnail():
    for name in ("geometry_isometric.png", "geometry_symmetric_fixed.png"):
        p = IMG_DIR / name
        if p.exists():
            print(f"  Geometry thumbnail: {p.name}")
            return imread(p)
    print("  ⚠ No geometry thumbnail found (skipping inset)")
    return None


# === 3D PATTERN GEOMETRY =====================================================

def build_pattern_surface(theta_deg, phi_deg, gain_dBi):
    """
    Convert (theta, phi, gain_dBi) to Cartesian XYZ for surface plot.
    Radius is gain shifted to be all-positive (visual balloon).
    Returns X, Y, Z, gain_for_color (all shape (Ntheta, Nphi)).
    """
    THETA, PHI = np.meshgrid(theta_deg, phi_deg, indexing="ij")
    th = np.deg2rad(THETA)
    ph = np.deg2rad(PHI)

    # Shift so min->0, peak stays at peak. Use a soft floor at -20 dBi for visual punch.
    floor_dB = max(np.nanmin(gain_dBi), np.nanmax(gain_dBi) - 25.0)
    g_clip = np.clip(gain_dBi, floor_dB, None)
    r = g_clip - floor_dB                       # all >= 0

    X = r * np.sin(th) * np.cos(ph)
    Y = r * np.sin(th) * np.sin(ph)
    Z = r * np.cos(th)
    return X, Y, Z, gain_dBi


# === FIGURE LAYOUT ===========================================================

def make_figure():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor="#0a0a0a")
    gs = GridSpec(
        2, 2,
        figure=fig,
        height_ratios=[1.0, 0.9],
        width_ratios=[1.0, 1.0],
        hspace=0.28, wspace=0.18,
        left=0.05, right=0.97, top=0.93, bottom=0.07,
    )
    ax_3d   = fig.add_subplot(gs[0, 0], projection="3d")
    ax_s11  = fig.add_subplot(gs[0, 1])
    ax_fam  = fig.add_subplot(gs[1, :])

    # Title
    fig.suptitle(
        "ANSYS HFSS  ×  PyAEDT  —  2.45 GHz Inset-Fed Patch Antenna",
        fontsize=20, color="white", weight="bold", y=0.985,
    )
    return fig, ax_3d, ax_s11, ax_fam


# === MAIN ====================================================================

def main():
    t0 = time.time()
    print("=" * 72)
    print(" PHASE 3b — LinkedIn Combo Animation")
    print("=" * 72)

    IMG_DIR.mkdir(parents=True, exist_ok=True)

    # -- Load all data
    print("\n[1/5] Loading data...")
    theta_deg, phi_deg, gain_dBi = load_farfield()
    f_s11, s11_dB                = load_s11_csv()
    family                       = load_phase2_family()
    geom_img                     = load_geometry_thumbnail()

    peak = float(np.nanmax(gain_dBi))
    ip, jp = np.unravel_index(np.nanargmax(gain_dBi), gain_dBi.shape)
    print(f"  Far-field peak (corrected): {peak:.2f} dBi at "
          f"θ={theta_deg[ip]:.1f}° φ={phi_deg[jp]:.1f}°")
    print(f"  S11 minimum: {s11_dB.min():.2f} dB at f="
          f"{f_s11[np.argmin(s11_dB)]:.4f} GHz")
    print(f"  Phase-2 family: {len(family['curves'])} curves, "
          f"optimum idx={family['optimum']}")

    # -- Build static 3D pattern surface (rotated by camera, no recompute)
    print("\n[2/5] Building 3D pattern surface...")
    X, Y, Z, G = build_pattern_surface(theta_deg, phi_deg, gain_dBi)
    R_max = max(float(np.max(np.abs(X))), float(np.max(np.abs(Y))), float(np.max(np.abs(Z))))

    # -- Create figure
    print("\n[3/5] Composing figure layout...")
    fig, ax_3d, ax_s11, ax_fam = make_figure()

    # ---- Panel A: 3D pattern (one-time draw, animate via view rotation)
    surf = ax_3d.plot_surface(
        X, Y, Z,
        facecolors=plt.cm.turbo((G - G.min()) / (G.max() - G.min() + 1e-9)),
        rstride=1, cstride=1, linewidth=0, antialiased=True, shade=False,
    )
    ax_3d.set_box_aspect([1, 1, 0.9])
    ax_3d.set_xlim(-R_max, R_max); ax_3d.set_ylim(-R_max, R_max); ax_3d.set_zlim(-R_max, R_max)
    ax_3d.set_xticks([]); ax_3d.set_yticks([]); ax_3d.set_zticks([])
    ax_3d.set_axis_off()
    ax_3d.set_title(f"3D Gain Pattern   peak ≈ {peak:.1f} dBi   @ {F0_GHZ} GHz",
                    color=ACCENT, fontsize=13, pad=-2, weight="bold")

    # Colorbar overlay (small, top-right of 3D panel)
    sm = plt.cm.ScalarMappable(cmap="turbo",
        norm=plt.Normalize(vmin=float(G.min()), vmax=float(G.max())))
    cbar = fig.colorbar(sm, ax=ax_3d, shrink=0.55, pad=0.02, aspect=18)
    cbar.set_label("Gain (dBi)", color="white", fontsize=10)
    cbar.ax.tick_params(colors="white", labelsize=9)
    cbar.outline.set_edgecolor(GRID_C)

    # ---- Panel B: S11 with sweeping cursor
    ax_s11.plot(f_s11, s11_dB, color=ACCENT, lw=2.2, label="|S11| (optimum)")
    ax_s11.axhline(-10, color="#888", ls="--", lw=1.0, alpha=0.7, label="−10 dB")
    ax_s11.set_xlim(f_s11.min(), f_s11.max())
    ax_s11.set_ylim(min(s11_dB.min() - 2, -32), 2)
    ax_s11.set_xlabel("Frequency (GHz)", color="white")
    ax_s11.set_ylabel("|S11| (dB)", color="white")
    ax_s11.set_title("Return Loss — Optimum Design",
                     color=ACCENT, fontsize=13, weight="bold")
    ax_s11.grid(True, color=GRID_C, alpha=0.5)
    ax_s11.legend(loc="lower right", facecolor="#101010", edgecolor=GRID_C, labelcolor="white", fontsize=9)
    # Animated cursor elements
    cursor_v   = ax_s11.axvline(f_s11[0], color=ACCENT2, lw=1.6, alpha=0.9)
    cursor_pt, = ax_s11.plot([f_s11[0]], [s11_dB[0]], "o",
                              color=ACCENT2, ms=9, mec="white", mew=1.0)
    cursor_txt = ax_s11.text(0.02, 0.05,  "", transform=ax_s11.transAxes,
                              color=ACCENT2, fontsize=11, weight="bold",
                              bbox=dict(facecolor="#101010", edgecolor=ACCENT2, boxstyle="round,pad=0.3"))

    # ---- Panel C: Family of curves
    cmap_fam = plt.cm.viridis(np.linspace(0.15, 0.95, len(family["curves"])))
    f_fam = family["f_GHz"]
    opt_idx = family["optimum"]
    for i, (label, curve, Lv) in enumerate(family["curves"]):
        is_opt = (i == opt_idx)
        ax_fam.plot(
            f_fam, curve,
            color=(ACCENT2 if is_opt else cmap_fam[i]),
            lw=(2.8 if is_opt else 1.4),
            alpha=(1.0 if is_opt else 0.75),
            label=(f"★ {label} (optimum)" if is_opt else label),
            zorder=(5 if is_opt else 2),
        )
    ax_fam.axhline(-10, color="#888", ls="--", lw=1.0, alpha=0.6)
    ax_fam.axvline(F0_GHZ, color="#888", ls=":", lw=1.0, alpha=0.6)
    ax_fam.set_xlim(f_fam.min(), f_fam.max())
    ax_fam.set_ylim(min(min(c[1].min() for c in family["curves"]) - 2, -32), 2)
    ax_fam.set_xlabel("Frequency (GHz)", color="white", fontsize=11)
    ax_fam.set_ylabel("|S11| (dB)", color="white", fontsize=11)
    ax_fam.set_title("Phase-2 Parametric Sweep — Patch Length L",
                     color=ACCENT, fontsize=13, weight="bold")
    ax_fam.grid(True, color=GRID_C, alpha=0.5)
    ax_fam.legend(loc="lower right", facecolor="#101010", edgecolor=GRID_C,
                  labelcolor="white", fontsize=9, ncol=2)

    # Geometry inset (top-left of bottom panel)
    if geom_img is not None:
        # Place axes relative to figure
        ax_inset = fig.add_axes([0.075, 0.10, 0.13, 0.18])
        ax_inset.imshow(geom_img)
        ax_inset.set_xticks([]); ax_inset.set_yticks([])
        for spine in ax_inset.spines.values():
            spine.set_color(ACCENT); spine.set_linewidth(1.2)
        ax_inset.set_title("Geometry", color=ACCENT, fontsize=9, pad=2)

    # Footnote
    fig.text(0.5, 0.015,
             "Half-symmetric HFSS model • +3 dB gain compensation applied "
             "(standard practice for wedge-modeled antennas)  •  Driven Modal • FR4 εr=4.4 • Inset-fed microstrip",
             ha="center", color="#9a9a9a", fontsize=9, style="italic")

    # === ANIMATION UPDATE ====================================================
    azim_start, azim_end = 30.0, 30.0 + 360.0     # full revolution over 8 s
    elev_start, elev_end = 25.0, 35.0             # gentle nod
    f_lo, f_hi = f_s11.min(), f_s11.max()

    def update(frame):
        u = frame / max(N_FRAMES - 1, 1)          # 0..1

        # --- 3D camera orbit
        ax_3d.view_init(elev=elev_start + (elev_end - elev_start) * u,
                        azim=azim_start + (azim_end - azim_start) * u)

        # --- S11 cursor sweep
        f_cur = f_lo + (f_hi - f_lo) * u
        # Find nearest sample
        k = int(np.argmin(np.abs(f_s11 - f_cur)))
        s_cur = float(s11_dB[k])
        cursor_v.set_xdata([f_s11[k], f_s11[k]])
        cursor_pt.set_data([f_s11[k]], [s_cur])
        cursor_txt.set_text(f"f = {f_s11[k]:.3f} GHz\n|S11| = {s_cur:.2f} dB")

        return cursor_v, cursor_pt, cursor_txt

    # === RENDER ==============================================================
    print(f"\n[4/5] Rendering {N_FRAMES} frames @ {FPS} fps "
          f"({DURATION_S:.1f} s, {FIGSIZE[0]*DPI}×{FIGSIZE[1]*DPI})...")

    anim = FuncAnimation(fig, update, frames=N_FRAMES, interval=1000.0/FPS, blit=False)

    # Try MP4 first
    wrote_path = None
    try:
        writer = FFMpegWriter(
            fps=FPS, codec="libx264",
            bitrate=8000,
            extra_args=["-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18"],
        )
        print(f"  Encoding MP4 → {OUT_MP4.name} ...")
        anim.save(
            str(OUT_MP4), writer=writer, dpi=DPI,
            savefig_kwargs={"facecolor": fig.get_facecolor()},   # preserve dark theme
            progress_callback=lambda i, n: print(f"    frame {i+1}/{n}", end="\r")
            if (i + 1) % 10 == 0 or i == n - 1 else None,
        )
        wrote_path = OUT_MP4
        print(f"\n  ✓ MP4 written: {OUT_MP4}")
    except Exception as e:
        print(f"\n  ⚠ MP4 failed: {e}")
        print(f"  Falling back to GIF → {OUT_GIF.name} ...")
        try:
            print("    (downscaling for GIF fallback...)")
            writer = PillowWriter(fps=15)                         # half framerate
            anim.save(str(OUT_GIF), writer=writer, dpi=60,         # ~960×540
                      savefig_kwargs={"facecolor": fig.get_facecolor()})
            wrote_path = OUT_GIF
            print(f"  ✓ GIF written: {OUT_GIF}")
        except Exception as e2:
            print(f"  ❌ GIF also failed: {e2}")

    plt.close(fig)

    # === DONE ================================================================
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