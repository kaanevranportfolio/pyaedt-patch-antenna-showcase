# =============================================================================
#  phase3a_field_capture.py
#  Module 12B — Phase 3a: Far-field capture at 2.45 GHz on optimum design
#  Outputs: csv/farfield_3d.npz (theta, phi, GainTotal_dBi grid)
# =============================================================================
from __future__ import annotations
import inspect, sys, time, traceback
from pathlib import Path
import numpy as np

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

F0_GHZ          = 2.45
THETA_STEP      = 2     # degrees — fine enough for smooth animation
PHI_STEP        = 2

(PROJECT_DIR / "csv").mkdir(parents=True, exist_ok=True)

# =============================================================================
def insert_full_sphere(hfss, name="FF_Full"):
    fn = hfss.insert_infinite_sphere
    sig = inspect.signature(fn); params = set(sig.parameters)
    KW_POOL = {
        "theta_start": 0,    "x_start": 0,
        "theta_stop": 180,   "x_stop": 180,
        "theta_step": THETA_STEP, "x_step": THETA_STEP,
        "phi_start": -180,   "y_start": -180,
        "phi_stop": 180,     "y_stop": 180,
        "phi_step": PHI_STEP, "y_step": PHI_STEP,
        "units": "deg", "name": name,
    }
    kwargs = {k: v for k, v in KW_POOL.items() if k in params}
    fn(**kwargs)
    print(f"    ✓ Sphere '{name}' (θ:0..180/{THETA_STEP}°, "
          f"φ:-180..180/{PHI_STEP}°)")

# =============================================================================
def _extract_data_array(sol, expr: str) -> np.ndarray:
    """Robustly extract magnitude data from SolutionData across PyAEDT versions."""
    # Try methods in order of preference
    for method_name in ("data_magnitude", "data_real", "data_magnitude_complex",
                        "_data_real", "data"):
        method = getattr(sol, method_name, None)
        if method is None:
            continue
        try:
            data = method(expr)
            arr = np.array(data, dtype=float)
            print(f"      → extracted via .{method_name}() ({arr.size} samples)")
            return arr
        except Exception as e:
            print(f"      → .{method_name}() failed: {e}")
            continue
    
    # Last resort: full attribute inspection
    print(f"    ⚠ All standard methods failed. Available attributes:")
    attrs = [a for a in dir(sol) if not a.startswith("_") and "data" in a.lower()]
    print(f"       {attrs}")
    raise AttributeError(
        f"Could not find a working data-extraction method on SolutionData. "
        f"Tried: data_magnitude, data_real, data_magnitude_complex, _data_real, data")


def extract_farfield_grid(hfss, setup_sweep, sphere_name):
    """Pull GainTotal grid via per-phi loop (reliable in PyAEDT 0.26.2)."""
    fn = hfss.post.get_solution_data
    
    print("    Using per-phi loop (more reliable than all-variations)...")
    phi_list = np.arange(-180.0, 181.0, PHI_STEP)
    
    # First cut to determine theta axis
    print(f"      Capturing reference cut at φ=0°...")
    cut0 = fn(
        expressions=["GainTotal"], setup_sweep_name=setup_sweep,
        context=sphere_name, report_category="Far Fields",
        primary_sweep_variable="Theta",
        variations={"Phi": ["0deg"]},
    )
    thetas = np.array(cut0.primary_sweep_values, dtype=float)
    n_theta_expected = int(180.0 / THETA_STEP) + 1   # 0..180 step 2 → 91
    
    if len(thetas) != n_theta_expected:
        print(f"      ⚠ Got {len(thetas)} theta samples, expected {n_theta_expected}")
    print(f"      θ axis: {len(thetas)} samples, range [{thetas[0]:.1f}, {thetas[-1]:.1f}]°")
    
    # Allocate gain grid
    gain_lin = np.zeros((len(thetas), len(phi_list)), dtype=float)
    
    # Capture phi=0 cut data we already retrieved
    gain_lin[:, np.argmin(np.abs(phi_list - 0.0))] = _extract_data_array(cut0, "GainTotal")
    
    print(f"      Looping over {len(phi_list)} phi values...")
    success_count = 1   # already have phi=0
    for j, ph in enumerate(phi_list):
        if abs(ph - 0.0) < 1e-6:
            continue   # already captured
        try:
            cut = fn(
                expressions=["GainTotal"], setup_sweep_name=setup_sweep,
                context=sphere_name, report_category="Far Fields",
                primary_sweep_variable="Theta",
                variations={"Phi": [f"{ph:g}deg"]},
            )
            cut_data = _extract_data_array(cut, "GainTotal")
            if len(cut_data) == len(thetas):
                gain_lin[:, j] = cut_data
                success_count += 1
            else:
                print(f"      ⚠ φ={ph}° size mismatch: got {len(cut_data)}, "
                      f"expected {len(thetas)}")
            if (j + 1) % 30 == 0:
                print(f"      progress: {j+1}/{len(phi_list)} phi values, "
                      f"{success_count} successful")
        except Exception as ee:
            print(f"      ⚠ φ={ph}° failed: {ee}")
    
    print(f"\n    ✓ Captured {success_count}/{len(phi_list)} phi cuts successfully")
    
    # Validate
    if success_count < 0.8 * len(phi_list):
        print(f"    ⚠ Less than 80% phi cuts succeeded — pattern will have gaps")
    
    # Convert to dBi
    gain_dBi = 10.0 * np.log10(np.clip(gain_lin, 1e-12, None))
    print(f"    Final grid: shape={gain_dBi.shape} (θ × φ)")
    print(f"    Gain range: {gain_dBi.min():.1f} to {gain_dBi.max():.1f} dBi")
    
    return thetas, phi_list, gain_dBi

# =============================================================================
def main() -> None:
    t0 = time.time()
    print("=" * 72)
    print(" PHASE 3a — Far-Field Capture at 2.45 GHz")
    print("=" * 72)

    hfss = Hfss(
        project=str(PROJECT_DIR / f"{PROJECT_NAME}.aedt"),
        design=DESIGN_NAME, version=AEDT_VERSION,
        non_graphical=False, new_desktop=True,
        student_version=STUDENT_EDITION,
    )
    print(f"    ✓ Opened project, patch_L = {hfss['patch_L']}")

    # ---------- Add field-capture setup at 2.45 GHz ------------------------
    print("\n[1/4] Adding field-capture setup at 2.45 GHz...")
    setup_name = "Setup_FF_2p45"
    
    # Clean up any prior version
    try:
        for s in hfss.setups:
            if s.name == setup_name:
                s.delete()
                print(f"    🧹 Deleted existing {setup_name}")
    except Exception:
        pass

    setup = hfss.create_setup(name=setup_name)
    setup.props["Frequency"]              = f"{F0_GHZ}GHz"
    setup.props["MaximumPasses"]          = 12
    setup.props["MinimumPasses"]          = 4
    setup.props["MinimumConvergedPasses"] = 2
    setup.props["MaxDeltaS"]              = 0.01
    setup.props["BasisOrder"]             = 1
    setup.update()
    print(f"    ✓ {setup_name} (ΔS=0.01, 4-12 passes)")

    # ---------- Insert full-sphere ------------------------------------------
    print("\n[2/4] Adding full-sphere infinite sphere...")
    try:
        for ff in hfss.field_setups:
            if ff.name == "FF_Full":
                ff.delete()
                print(f"    🧹 Deleted existing FF_Full")
                break
    except Exception:
        pass
    insert_full_sphere(hfss, "FF_Full")

    # ---------- Solve -------------------------------------------------------
    print(f"\n[3/4] Solving (~2-4 min)...")
    t_solve = time.time()
    hfss.analyze(cores=NUM_CORES, setup=setup_name)
    print(f"    ✓ Solved in {(time.time()-t_solve)/60:.2f} min")
    hfss.save_project()

    # ---------- Extract far-field grid --------------------------------------
    print(f"\n[4/4] Extracting full-sphere gain pattern...")
    last_adapt = f"{setup_name} : LastAdaptive"
    thetas, phis, gain_dBi = extract_farfield_grid(
        hfss, last_adapt, "FF_Full")

    peak_dBi = float(np.nanmax(gain_dBi))
    i_pk, j_pk = np.unravel_index(np.nanargmax(gain_dBi), gain_dBi.shape)
    th_pk, ph_pk = float(thetas[i_pk]), float(phis[j_pk])
    print(f"\n  📡 Peak gain: {peak_dBi:.2f} dBi at θ={th_pk:.1f}° φ={ph_pk:.1f}°")

    # Save
    out_npz = PROJECT_DIR / "csv" / "farfield_3d.npz"
    np.savez_compressed(
        out_npz,
        theta_deg=thetas, phi_deg=phis, gain_dBi=gain_dBi,
        f0_GHz=F0_GHZ,
        peak_dBi=peak_dBi, peak_theta=th_pk, peak_phi=ph_pk,
    )
    print(f"\n💾 {out_npz.name}: shape={gain_dBi.shape}, "
          f"peak={peak_dBi:.2f} dBi")
    print(f"   ({out_npz.stat().st_size / 1024:.1f} KB)")

    print(f"\n  ✅ Phase 3a done in {(time.time()-t0)/60:.2f} min")
    print(f"  Ready for Phase 3b: animation rendering (no AEDT needed)")

    hfss.save_project()
    hfss.release_desktop(close_projects=False, close_desktop=False)

if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc(); sys.exit(1)