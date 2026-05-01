# =============================================================================
#  patch_2p45GHz_v2_showcase.py
#  Module 12B — LinkedIn Showcase Build (Phase 1)
#  Inset-fed microstrip patch antenna at 2.45 GHz on FR4
#  Adds: inset feed, far-field sphere, E-field setup, convergence tracking
# =============================================================================
from __future__ import annotations
import inspect, json, os, sys, time, traceback
from pathlib import Path
from typing import Dict, List

import numpy as np

# ---- matplotlib --------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ---- PyAEDT ------------------------------------------------------------------
from ansys.aedt.core import Hfss

# =============================================================================
# QUIRK 1 — Student-Edition '2025.2SV' monkey-patch
# =============================================================================
import ansys.aedt.core.desktop as _aedt_desktop
_orig_check = _aedt_desktop.Desktop.check_starting_mode
def _patched_check(self):
    if isinstance(getattr(self, "aedt_version_id", None), str) \
            and self.aedt_version_id.upper().endswith("SV"):
        self.aedt_version_id = self.aedt_version_id[:-2]
    return _orig_check(self)
_aedt_desktop.Desktop.check_starting_mode = _patched_check
print("✓ Applied Student-Edition 'SV' compatibility patch")

# =============================================================================
# USER FLAGS
# =============================================================================
NON_GRAPHICAL    = False
REVIEW_GEOMETRY  = True
AEDT_VERSION     = "2025.2"
STUDENT_EDITION  = True
NUM_CORES        = 4
PROJECT_DIR      = Path.cwd() / "patch_showcase"
PROJECT_NAME     = "Patch_2p45GHz_Showcase"
DESIGN_NAME      = "Patch_InsetFed"

for sub in ("csv", "img", "linkedin"):
    (PROJECT_DIR / sub).mkdir(parents=True, exist_ok=True)

# =============================================================================
# DESIGN CONSTANTS — TUNED for inset feed at 2.45 GHz
# =============================================================================
F0_GHZ      = 2.45
F_MIN       = 2.0
F_MAX       = 3.0
F_PTS       = 401          # finer for cleaner Smith chart

SUB_W       = 60.0
SUB_L       = 60.0
SUB_H       = 1.6
SUB_ER      = 4.4

# Patch tuned slightly shorter to land on 2.45 (compensate fringing seen in v1)
PATCH_W     = 38.0
PATCH_L     = 28.2          # was 29.0 → shorter to push f_res up to 2.45

# Inset feed dimensions
FEED_W      = 3.0
FEED_L      = 16.0
INSET_DEPTH = 9.0           # how deep into patch (Y-direction)
INSET_GAP   = 1.0           # lateral gap on each side of feed inside patch

AIR_PAD     = 35.0

# Derived coordinates
PATCH_X0    = -PATCH_W / 2.0
PATCH_Y0    = -PATCH_L / 2.0
FEED_X0     = -FEED_W / 2.0
FEED_Y0     = -SUB_L / 2.0
SUB_X0      = -SUB_W / 2.0
SUB_Y0      = -SUB_L / 2.0

# Inset notch coordinates (cut from patch, two rectangles around feed)
NOTCH_Y0    = PATCH_Y0           # at the feed-side edge
NOTCH_W     = (FEED_W / 2.0) + INSET_GAP   # half-width of notch
NOTCH_L     = INSET_DEPTH

# Air box
AIR_X0 = SUB_X0 - AIR_PAD
AIR_Y0 = SUB_Y0
AIR_Z0 = -AIR_PAD
AIR_DX = SUB_W + 2 * AIR_PAD
AIR_DY = SUB_L + AIR_PAD
AIR_DZ = SUB_H + 2 * AIR_PAD

# Port sheet
PORT_W      = 5.0 * FEED_W
PORT_H      = 6.0 * SUB_H
PORT_X0     = -PORT_W / 2.0
PORT_Y      = AIR_Y0
PORT_Z0     = 0.0

print(f"\n📐 Inset-fed patch geometry:")
print(f"   Patch:     {PATCH_W}×{PATCH_L} mm")
print(f"   Feed:      {FEED_W}×{FEED_L} mm")
print(f"   Inset:     depth={INSET_DEPTH} mm, gap={INSET_GAP} mm")

# =============================================================================
# WAVE PORT (same pattern as v1 — proven working)
# =============================================================================
def assign_wave_port(hfss, port_sheet) -> str:
    face_id = port_sheet.faces[0].id
    inset = SUB_H * 0.02
    p_lo = [0.0, PORT_Y, 0.0 + inset]
    p_hi = [0.0, PORT_Y, SUB_H - inset]

    fn = hfss.wave_port
    sig = inspect.signature(fn); params = set(sig.parameters)
    KW_POOL = {
        "assignment": face_id, "signal": face_id, "reference": None,
        "create_port_sheet": False, "integration_line": [p_lo, p_hi],
        "impedance": 50, "name": "P1", "renormalize": True,
        "deembed": False, "num_modes": 1, "modes": 1, "is_microstrip": True,
    }
    kwargs = {k: v for k, v in KW_POOL.items() if k in params}
    bnd = fn(**kwargs)
    if not bnd:
        raise RuntimeError("wave_port returned falsy")
    print(f"    ✓ Wave port assigned (microstrip TEM)")
    return getattr(bnd, "name", "P1")

# =============================================================================
# INFINITE SPHERE (full sphere for 3D pattern animation)
# =============================================================================
def insert_full_sphere(hfss, name="FF_Full"):
    fn = hfss.insert_infinite_sphere
    sig = inspect.signature(fn); params = set(sig.parameters)
    KW_POOL = {
        "theta_start": 0,    "x_start": 0,
        "theta_stop": 180,   "x_stop": 180,
        "theta_step": 2,     "x_step": 2,
        "phi_start": -180,   "y_start": -180,
        "phi_stop": 180,     "y_stop": 180,
        "phi_step": 2,       "y_step": 2,
        "units": "deg", "name": name,
    }
    kwargs = {k: v for k, v in KW_POOL.items() if k in params}
    fn(**kwargs)
    print(f"    ✓ Infinite sphere '{name}' (θ:0..180/2, φ:-180..180/2)")

# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    t0 = time.time()
    print("=" * 72)
    print(" PATCH ANTENNA @ 2.45 GHz — INSET FEED (LinkedIn Showcase v1)")
    print("=" * 72)

    hfss = Hfss(
        project=str(PROJECT_DIR / f"{PROJECT_NAME}.aedt"),
        design=DESIGN_NAME,
        solution_type="Modal",
        version=AEDT_VERSION,
        non_graphical=NON_GRAPHICAL,
        new_desktop=True,
        student_version=STUDENT_EDITION,
    )
    hfss.modeler.model_units = "mm"

    # Idempotent purge
    try:
        existing = list(hfss.modeler.object_names)
        if existing:
            hfss.modeler.delete(existing)
            print(f"    🧹 Purged {len(existing)} stale objects")
    except Exception:
        pass
    try:
        for bnd in list(getattr(hfss, "boundaries", []) or []):
            try: hfss.delete_boundary(getattr(bnd, "name", str(bnd)))
            except Exception: pass
    except Exception:
        pass

    # ---------------- 1. Variables (parametric tree)
    print("\n[1/9] Pushing variables...")
    for k, v in {
        "f0":      f"{F0_GHZ}GHz",
        "patch_W": f"{PATCH_W}mm",
        "patch_L": f"{PATCH_L}mm",
        "feed_W":  f"{FEED_W}mm",
        "inset_d": f"{INSET_DEPTH}mm",
        "inset_g": f"{INSET_GAP}mm",
    }.items():
        hfss[k] = v
    print(f"    ✓ Variables registered")

    # ---------------- 2. Geometry
    print("\n[2/9] Building geometry with inset feed...")
    
    # Substrate
    hfss.modeler.create_box(
        origin=[SUB_X0, SUB_Y0, 0.0], sizes=[SUB_W, SUB_L, SUB_H],
        name="Substrate", material="FR4_epoxy",
    )

    # Ground sheet
    hfss.modeler.create_rectangle(
        orientation="XY", origin=[SUB_X0, SUB_Y0, 0.0],
        sizes=[SUB_W, SUB_L], name="Ground",
    )

    # Patch sheet
    hfss.modeler.create_rectangle(
        orientation="XY", origin=[PATCH_X0, PATCH_Y0, SUB_H],
        sizes=[PATCH_W, PATCH_L], name="Patch",
    )

    # Two notch rectangles to subtract from patch (inset feed slots)
    notch_left = hfss.modeler.create_rectangle(
        orientation="XY",
        origin=[-FEED_W/2.0 - INSET_GAP, PATCH_Y0, SUB_H],
        sizes=[INSET_GAP, INSET_DEPTH], name="NotchL",
    )
    notch_right = hfss.modeler.create_rectangle(
        orientation="XY",
        origin=[FEED_W/2.0, PATCH_Y0, SUB_H],
        sizes=[INSET_GAP, INSET_DEPTH], name="NotchR",
    )
    hfss.modeler.subtract("Patch", ["NotchL", "NotchR"], keep_originals=False)
    print(f"    ✓ Inset notches subtracted from patch")

    # Feed sheet (extends from substrate edge into the inset slot)
    hfss.modeler.create_rectangle(
        orientation="XY", origin=[FEED_X0, FEED_Y0, SUB_H],
        sizes=[FEED_W, FEED_L], name="Feed",
    )
    hfss.modeler.unite(["Patch", "Feed"])
    print(f"    ✓ Patch ∪ Feed united (with inset)")

    hfss.assign_perfect_e(["Ground"], name="PEC_Ground")
    hfss.assign_perfect_e(["Patch"], name="PEC_PatchFeed")
    print(f"    ✓ Perfect E assigned")

    # AirBox + radiation
    hfss.modeler.create_box(
        origin=[AIR_X0, AIR_Y0, AIR_Z0], sizes=[AIR_DX, AIR_DY, AIR_DZ],
        name="AirBox", material="air",
    )
    hfss.assign_radiation_boundary_to_objects("AirBox", name="Rad_Outer")
    print(f"    ✓ Radiation boundary on AirBox")

    # Port sheet
    port_sheet = hfss.modeler.create_rectangle(
        orientation="XZ", origin=[PORT_X0, PORT_Y, PORT_Z0],
        sizes=[PORT_W, PORT_H], name="PortSheet",
    )

    # ---------------- 3. Wave port
    print("\n[3/9] Wave port...")
    port_name = assign_wave_port(hfss, port_sheet)

    # ---------------- 4. Setup + sweep
    print("\n[4/9] Setup + sweep...")
    setup = hfss.create_setup(name="Setup1")
    setup.props["Frequency"]              = f"{F0_GHZ}GHz"
    setup.props["MaximumPasses"]          = 15
    setup.props["MinimumPasses"]          = 4
    setup.props["MinimumConvergedPasses"] = 2
    setup.props["MaxDeltaS"]              = 0.015
    setup.props["BasisOrder"]             = 1
    setup.update()
    print(f"    ✓ Setup1 @ {F0_GHZ} GHz, ΔS=0.015, 4-15 passes")

    hfss.create_linear_count_sweep(
        setup="Setup1", unit="GHz",
        start_frequency=F_MIN, stop_frequency=F_MAX,
        num_of_freq_points=F_PTS, name="Sweep1",
        save_fields=False, save_rad_fields=True,    # need rad fields for FF!
        sweep_type="Interpolating",
    )
    print(f"    ✓ Sweep1: {F_MIN}-{F_MAX} GHz, {F_PTS} pts")

    # ---------------- 5. Far-field sphere
    print("\n[5/9] Inserting full-sphere far-field setup...")
    insert_full_sphere(hfss, "FF_Full")

    # ---------------- 6. Validate + screenshot
    print("\n[6/9] Validate + screenshot...")
    try: hfss.validate_simple()
    except Exception as e: print(f"    ⚠ {e}")
    try:
        hfss.modeler.fit_all()
        hfss.post.export_model_picture(
            full_name=str(PROJECT_DIR / "img" / "geometry_isometric.png"),
            width=1920, height=1080)
        print(f"    📸 geometry_isometric.png saved")
    except Exception as e:
        print(f"    ⚠ screenshot: {e}")

    if REVIEW_GEOMETRY and not NON_GRAPHICAL:
        print("\n" + "─" * 72)
        print("  REVIEW the inset-fed patch geometry in AEDT.")
        print("  You should see TWO notches cut into the patch around the feed.")
        print("─" * 72)
        try:
            input("  ▶ Press Enter to solve  (Ctrl-C to abort)... ")
        except KeyboardInterrupt:
            hfss.save_project(); return

    # ---------------- 7. Solve
    print("\n[7/9] Solving (3-7 min typical)...")
    t_solve = time.time()
    hfss.analyze(cores=NUM_CORES, setup="Setup1")
    print(f"    ✓ Solve done in {(time.time()-t_solve)/60:.2f} min")
    hfss.save_project()

    # ---------------- 8. Post-process: S11
    print("\n[8/9] Extracting S11...")
    sol = hfss.post.get_solution_data(
        expressions=[f"dB(S({port_name},{port_name}))"],
        setup_sweep_name="Setup1 : Sweep1",
        primary_sweep_variable="Freq",
    )
    f_ghz = np.array(sol.primary_sweep_values, dtype=float)
    s11_db = np.array(sol.data_real(f"dB(S({port_name},{port_name}))"), dtype=float)
    
    i_min = int(np.argmin(s11_db))
    f_res = float(f_ghz[i_min]); s11_min = float(s11_db[i_min])
    
    # -10 dB bandwidth
    below_10 = s11_db < -10.0
    if below_10.any():
        idx = np.where(below_10)[0]
        bw_low, bw_high = float(f_ghz[idx[0]]), float(f_ghz[idx[-1]])
        bw_mhz = (bw_high - bw_low) * 1000.0
    else:
        bw_low = bw_high = bw_mhz = float("nan")

    metrics = {
        "f_res_GHz": f_res, "s11_min_dB": s11_min,
        "bw_10dB_MHz": bw_mhz, "bw_low_GHz": bw_low, "bw_high_GHz": bw_high,
        "wall_time_min": (time.time() - t0) / 60.0,
    }

    # ---------------- 9. Save outputs
    print("\n[9/9] Saving CSV + JSON + plots...")
    np.savetxt(PROJECT_DIR / "csv" / "S11_dB.csv",
               np.column_stack([f_ghz, s11_db]),
               delimiter=",", header="Freq_GHz,S11_dB", comments="")
    
    (PROJECT_DIR / "csv" / "metrics.json").write_text(json.dumps(metrics, indent=2))

    if HAS_MPL:
        # Professional white theme for S11 plot
        fig, ax = plt.subplots(figsize=(10, 5.5), dpi=130)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FAFAFA")
        
        # S11 curve: deep professional blue
        ax.plot(f_ghz, s11_db, lw=2.4, color="#0066CC", label="|S11|")
        
        # −10 dB reference line: dashed gray
        ax.axhline(-10, color="#666666", ls="--", lw=1.2, alpha=0.7, label="−10 dB")
        
        # Shade region where |S11| < −10 dB (blue, alpha 0.15)
        if not np.isnan(bw_low):
            ax.axvspan(bw_low, bw_high, alpha=0.15, color="#0066CC",
                       label=f"BW = {bw_mhz:.1f} MHz")
        
        # Resonance marker: gold dot with white edge
        ax.plot(f_res, s11_min, marker="o", markersize=10, 
                color="#D4A017", markeredgecolor="white", markeredgewidth=1.5,
                linestyle="none")
        
        # Annotation box for resonance
        annotation_text = f"f₀ = {f_res:.3f} GHz\n|S11| = {s11_min:.2f} dB"
        ax.annotate(annotation_text,
                    xy=(f_res, s11_min), xytext=(f_res + 0.3, s11_min + 5),
                    fontsize=9, color="#D4A017", weight="bold",
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="white", 
                             edgecolor="#D4A017", linewidth=1.5),
                    arrowprops=dict(arrowstyle="->", color="#D4A017", lw=1.2))
        
        # Labels and title
        ax.set_xlabel("Frequency (GHz)", fontsize=11, color="#222222")
        ax.set_ylabel("|S11| (dB)", fontsize=11, color="#222222")
        ax.set_title("Return Loss — Optimum Design", fontsize=14, color="#0066CC", weight="bold")
        
        # Y-axis limit
        ax.set_ylim(min(s11_db.min() - 2, -35), 2)
        
        # Grid: light gray
        ax.grid(True, alpha=0.7, color="#CCCCCC", linestyle="-", linewidth=0.8)
        
        # Spines: medium gray
        for spine in ax.spines.values():
            spine.set_color("#666666")
            spine.set_linewidth(1.0)
        
        # Ticks: dark gray
        ax.tick_params(colors="#222222", labelsize=10)
        
        # Legend with white background
        ax.legend(loc="upper right", framealpha=0.95, facecolor="white",
                  edgecolor="#CCCCCC", frameon=True)
        
        fig.tight_layout()
        fig.savefig(PROJECT_DIR / "img" / "S11_showcase.png",
                    dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
        plt.close(fig)
        print(f"    ✓ S11_showcase.png saved")

    # Touchstone
    try:
        hfss.export_touchstone(setup="Setup1", sweep="Sweep1",
            output_file=str(PROJECT_DIR / "csv" / "patch_inset.s2p"))
        print(f"    ✓ Touchstone saved")
    except Exception as e:
        print(f"    ⚠ {e}")

    # =================== RESULTS ===================
    print("\n" + "=" * 72)
    print(" RESULTS — INSET-FED PATCH @ 2.45 GHz")
    print("=" * 72)
    print(f"  Resonant frequency : {f_res:.4f} GHz   (target: {F0_GHZ} GHz)")
    print(f"  Frequency error    : {(f_res - F0_GHZ)*1000:+.1f} MHz")
    print(f"  Min |S11|          : {s11_min:6.2f} dB")
    print(f"  -10 dB BW          : {bw_mhz:.1f} MHz  ({bw_low:.3f} – {bw_high:.3f} GHz)")
    print(f"  Wall time          : {metrics['wall_time_min']:.2f} min")
    print("=" * 72)
    print(f"\n📁 All outputs in: {PROJECT_DIR}")

    hfss.save_project()
    hfss.release_desktop(close_projects=False, close_desktop=NON_GRAPHICAL)
    print("\n✅ Phase 1 done. Ready for Phase 2 (parametric heatmap) or Phase 3 (visuals).")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n" + "!" * 72)
        traceback.print_exc()
        sys.exit(1)