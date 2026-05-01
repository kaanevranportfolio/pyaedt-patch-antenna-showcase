# =============================================================================
#  phase2_param_sweep.py  (CORRECTED — rebuilds patch geometry per iteration)
# =============================================================================
from __future__ import annotations
import json, sys, time, traceback
from pathlib import Path
import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from ansys.aedt.core import Hfss

# --- SV monkey-patch ---
import ansys.aedt.core.desktop as _aedt_desktop
_orig_check = _aedt_desktop.Desktop.check_starting_mode
def _patched_check(self):
    if isinstance(getattr(self, "aedt_version_id", None), str) \
            and self.aedt_version_id.upper().endswith("SV"):
        self.aedt_version_id = self.aedt_version_id[:-2]
    return _orig_check(self)
_aedt_desktop.Desktop.check_starting_mode = _patched_check

# === CONFIG ==================================================================
AEDT_VERSION    = "2025.2"
STUDENT_EDITION = True
NUM_CORES       = 4
PROJECT_DIR     = Path.cwd() / "patch_showcase"
PROJECT_NAME    = "Patch_2p45GHz_Showcase"
DESIGN_NAME     = "Patch_InsetFed"

PATCH_L_VALUES  = [27.8, 28.0, 28.2, 28.4, 28.6]
F0_GHZ          = 2.45

# Fixed geometry constants (must match Phase 1)
SUB_H        = 1.6
PATCH_W      = 38.0
FEED_W       = 3.0
FEED_L       = 16.0
INSET_DEPTH  = 9.0
INSET_GAP    = 1.0
SUB_L        = 60.0

(PROJECT_DIR / "csv").mkdir(parents=True, exist_ok=True)
(PROJECT_DIR / "img").mkdir(parents=True, exist_ok=True)

# =============================================================================
def rebuild_patch(hfss, patch_L: float) -> None:
    """Delete existing Patch object and rebuild with new patch_L."""
    # Delete patch (which absorbed Feed via unite in Phase 1)
    try:
        existing = list(hfss.modeler.object_names)
        for obj_name in ["Patch", "Feed", "NotchL", "NotchR"]:
            if obj_name in existing:
                hfss.modeler.delete([obj_name])
    except Exception as e:
        print(f"    (delete warning: {e})")
    
    # Delete the old PEC_PatchFeed boundary (will be re-assigned)
    try:
        for bnd in list(getattr(hfss, "boundaries", []) or []):
            bn = getattr(bnd, "name", str(bnd))
            if "PatchFeed" in bn or bn.startswith("PerfE_2"):
                try: hfss.delete_boundary(bn)
                except Exception: pass
    except Exception:
        pass

    # Derived coords (using current patch_L)
    PATCH_X0 = -PATCH_W / 2.0
    PATCH_Y0 = -patch_L / 2.0
    FEED_X0  = -FEED_W / 2.0
    FEED_Y0  = -SUB_L / 2.0

    # Patch
    hfss.modeler.create_rectangle(
        orientation="XY", origin=[PATCH_X0, PATCH_Y0, SUB_H],
        sizes=[PATCH_W, patch_L], name="Patch",
    )
    # Notches
    hfss.modeler.create_rectangle(
        orientation="XY",
        origin=[-FEED_W/2.0 - INSET_GAP, PATCH_Y0, SUB_H],
        sizes=[INSET_GAP, INSET_DEPTH], name="NotchL",
    )
    hfss.modeler.create_rectangle(
        orientation="XY",
        origin=[FEED_W/2.0, PATCH_Y0, SUB_H],
        sizes=[INSET_GAP, INSET_DEPTH], name="NotchR",
    )
    hfss.modeler.subtract("Patch", ["NotchL", "NotchR"], keep_originals=False)
    # Feed
    hfss.modeler.create_rectangle(
        orientation="XY", origin=[FEED_X0, FEED_Y0, SUB_H],
        sizes=[FEED_W, FEED_L], name="Feed",
    )
    hfss.modeler.unite(["Patch", "Feed"])
    # Re-assign PEC
    hfss.assign_perfect_e(["Patch"], name="PEC_PatchFeed")

# =============================================================================
def main() -> None:
    t0 = time.time()
    print("=" * 72)
    print(f" PHASE 2 — Parametric Sweep (geometry rebuild per iter)")
    print(f" PATCH_L values: {PATCH_L_VALUES} mm")
    print("=" * 72)

    hfss = Hfss(
        project=str(PROJECT_DIR / f"{PROJECT_NAME}.aedt"),
        design=DESIGN_NAME, version=AEDT_VERSION,
        non_graphical=False, new_desktop=True,
        student_version=STUDENT_EDITION,
    )
    print(f"    ✓ Opened project")

    results = []

    for i, L_val in enumerate(PATCH_L_VALUES):
        print(f"\n--- [{i+1}/{len(PATCH_L_VALUES)}] PATCH_L = {L_val} mm ---")
        
        # REBUILD geometry with new L
        print(f"    Rebuilding patch geometry...")
        rebuild_patch(hfss, L_val)
        print(f"    ✓ Geometry rebuilt with L={L_val} mm")
        
        # Solve
        t_solve = time.time()
        hfss.analyze(cores=NUM_CORES, setup="Setup1")
        print(f"    ✓ Solved in {(time.time()-t_solve)/60:.2f} min")

        # Extract S11
        sol = hfss.post.get_solution_data(
            expressions=["dB(S(P1,P1))"],
            setup_sweep_name="Setup1 : Sweep1",
            primary_sweep_variable="Freq",
        )
        f_ghz = np.array(sol.primary_sweep_values, dtype=float)
        s11_db = np.array(sol.data_real("dB(S(P1,P1))"), dtype=float)
        i_min = int(np.argmin(s11_db))
        f_res = float(f_ghz[i_min]); s11_min = float(s11_db[i_min])

        below_10 = s11_db < -10.0
        if below_10.any():
            idx = np.where(below_10)[0]
            bw_mhz = float(f_ghz[idx[-1]] - f_ghz[idx[0]]) * 1000.0
        else:
            bw_mhz = 0.0

        print(f"    f_res = {f_res:.4f} GHz  (Δ={(f_res-F0_GHZ)*1000:+.1f} MHz)")
        print(f"    |S11|_min = {s11_min:.2f} dB,  BW = {bw_mhz:.1f} MHz")

        results.append({
            "patch_L_mm": L_val, "f_res_GHz": f_res,
            "s11_min_dB": s11_min, "bw_mhz": bw_mhz,
            "freqs_GHz": f_ghz.tolist(), "s11_dB": s11_db.tolist(),
        })

    # ---------- Pick optimum ------------------------------------------------
    valid = [r for r in results if r["s11_min_dB"] < -15.0]
    if not valid: valid = results
    optimum = min(valid, key=lambda r: abs(r["f_res_GHz"] - F0_GHZ))

    print("\n" + "=" * 72)
    print(" PARAMETRIC SWEEP RESULTS")
    print("=" * 72)
    print(f"  {'PATCH_L':>9s} | {'f_res':>11s} | {'Δf':>9s} | {'|S11|':>9s} | {'BW':>8s}")
    print("  " + "-" * 60)
    for r in results:
        mark = "  ★" if r is optimum else ""
        print(f"  {r['patch_L_mm']:>7.1f}mm | {r['f_res_GHz']:>9.4f}GHz | "
              f"{(r['f_res_GHz']-F0_GHZ)*1000:>+7.1f}MHz | "
              f"{r['s11_min_dB']:>7.2f}dB | {r['bw_mhz']:>5.1f}MHz{mark}")

    print(f"\n  🏆 OPTIMUM: PATCH_L = {optimum['patch_L_mm']} mm")
    print(f"     f_res = {optimum['f_res_GHz']:.4f} GHz")
    print(f"     |S11| = {optimum['s11_min_dB']:.2f} dB")

    # ---------- Set optimum and save ----------------------------------------
    print(f"\n  Rebuilding final geometry with optimum L={optimum['patch_L_mm']} mm...")
    rebuild_patch(hfss, optimum["patch_L_mm"])
    hfss.save_project()
    print(f"  ✓ Project saved with optimum design")

    # ---------- JSON + NPZ --------------------------------------------------
    summary = {
        "results": [{k: v for k, v in r.items() 
                     if k not in ("freqs_GHz", "s11_dB")} for r in results],
        "optimum": {k: v for k, v in optimum.items()
                    if k not in ("freqs_GHz", "s11_dB")},
        "wall_time_min": (time.time() - t0) / 60.0,
    }
    (PROJECT_DIR / "csv" / "phase2_summary.json").write_text(
        json.dumps(summary, indent=2))
    np.savez_compressed(
        PROJECT_DIR / "csv" / "phase2_curves.npz",
        patch_L_values=np.array(PATCH_L_VALUES),
        freqs_GHz=np.array(results[0]["freqs_GHz"]),
        s11_dB_matrix=np.array([r["s11_dB"] for r in results]),
    )
    print(f"💾 phase2_summary.json + phase2_curves.npz saved")

    # ---------- Plot for PDF ------------------------------------------------
    if HAS_MPL:
        fig, ax = plt.subplots(figsize=(11, 6), dpi=140)
        
        # White theme
        fig.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FAFAFA")
        
        # Viridis colormap sampled from 0.15 to 0.85
        cmap = plt.get_cmap("viridis")
        cmap_range = np.linspace(0.15, 0.85, len(results))
        
        for i, r in enumerate(results):
            is_opt = r is optimum
            if is_opt:
                color = "#D4A017"
                lw = 2.8
                alpha = 1.0
                zorder = 5
                label = f"★ L={r['patch_L_mm']}mm"
            else:
                color = cmap(cmap_range[i])
                lw = 1.6
                alpha = 0.85
                zorder = 2
                label = f"L={r['patch_L_mm']}mm"
            
            ax.plot(r["freqs_GHz"], r["s11_dB"],
                    color=color, lw=lw, alpha=alpha, zorder=zorder,
                    label=label)
        
        # Reference lines
        ax.axhline(-10, color="#666666", ls="--", lw=1.0, alpha=0.6)
        ax.axvline(F0_GHZ, color="#666666", ls=":", lw=1.0, alpha=0.6)
        
        # Labels and title
        ax.set_xlabel("Frequency (GHz)", fontsize=11, color="#222222")
        ax.set_ylabel("|S11| (dB)", fontsize=11, color="#222222")
        ax.set_title("Parametric Sweep — Patch Length L", fontsize=14,
                      color="#0066CC", fontweight="bold")
        
        # Axes styling
        ax.set_ylim(-35, 2)
        ax.grid(True, color="#CCCCCC", alpha=0.7)
        
        # Tick labels
        ax.tick_params(colors="#222222")
        
        # Spines
        for spine in ax.spines.values():
            spine.set_color("#666666")
            spine.set_linewidth(1.0)
        
        # Legend
        ax.legend(loc="lower right", framealpha=1.0, fontsize=9,
                  facecolor="white", edgecolor="#CCCCCC",
                  frameon=True, ncol=2)
        for text in ax.get_legend().get_texts():
            text.set_color("#222222")
        
        fig.tight_layout()
        fig.savefig(PROJECT_DIR / "img" / "phase2_family_of_curves.png",
                    dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"💾 phase2_family_of_curves.png saved")

    print(f"\n  ✅ Phase 2 done in {(time.time()-t0)/60:.2f} min")
    print(f"  Optimum patch_L = {optimum['patch_L_mm']} mm baked into project")
    
    hfss.save_project()
    hfss.release_desktop(close_projects=False, close_desktop=False)

if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc(); sys.exit(1)