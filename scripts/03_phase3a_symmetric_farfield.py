# =============================================================================
#  phase3a_v3_symmetric_fixed.py
#  Half-symmetric model. Radiation ONLY on outer 5 faces (NOT x=0 plane).
#  Pattern adopted from horn project's classify_air_faces().
# =============================================================================
from __future__ import annotations
import inspect, sys, time, traceback
from pathlib import Path
import numpy as np
from ansys.aedt.core import Hfss

# --- SV monkey-patch ---
import ansys.aedt.core.desktop as _aedt_desktop
_orig = _aedt_desktop.Desktop.check_starting_mode
def _patched(self):
    if isinstance(getattr(self, "aedt_version_id", None), str) \
            and self.aedt_version_id.upper().endswith("SV"):
        self.aedt_version_id = self.aedt_version_id[:-2]
    return _orig(self)
_aedt_desktop.Desktop.check_starting_mode = _patched

# === CONFIG ==================================================================
PROJECT_DIR  = Path.cwd() / "patch_showcase"
PROJECT_NAME = "Patch_2p45GHz_Showcase"
DESIGN_NAME  = "Patch_InsetFed_Symmetric"
F0_GHZ, PHI_STEP, THETA_STEP = 2.45, 2, 2

# Geometry (half model, x ≥ 0)
SUB_W, SUB_L, SUB_H = 60.0, 60.0, 1.6
PATCH_W, PATCH_L = 38.0, 28.4
FEED_W, FEED_L = 3.0, 16.0
INSET_DEPTH, INSET_GAP = 9.0, 1.0
AIR_PAD = 35.0

(PROJECT_DIR / "csv").mkdir(parents=True, exist_ok=True)
(PROJECT_DIR / "img").mkdir(parents=True, exist_ok=True)

# =============================================================================
def _extract(sol, expr):
    for m in ("data_real", "data_magnitude_complex", "data"):
        f = getattr(sol, m, None)
        if f is None: continue
        try: return np.array(f(expr), dtype=float)
        except Exception: continue
    raise AttributeError(f"No extractor for {expr}")

def classify_airbox_faces(hfss, body_name="AirBox", tol=0.5):
    """YOUR pattern: classify by centroid. Returns sym_x0 + radiation faces."""
    body = hfss.modeler[body_name]
    out = {"sym_x0": [], "radiation": []}
    print(f"    Classifying {len(body.faces)} faces of {body_name}...")
    for f in body.faces:
        cx, cy, cz = f.center
        if abs(cx) < tol:
            out["sym_x0"].append(f.id)
            print(f"      [SYM] face id={f.id} at ({cx:.1f},{cy:.1f},{cz:.1f})")
        else:
            out["radiation"].append(f.id)
    print(f"    → sym_x0={len(out['sym_x0'])}, radiation={len(out['radiation'])}")
    if len(out["sym_x0"]) != 1 or len(out["radiation"]) != 5:
        print(f"    ⚠ Expected 1 sym + 5 rad faces!")
    return out

def _assign_sym(hfss, face_ids, is_pec, name):
    fn = hfss.assign_symmetry
    sig = inspect.signature(fn); params = set(sig.parameters)
    kw = {}
    if "assignment" in params: kw["assignment"] = face_ids
    elif "faces" in params: kw["faces"] = face_ids
    elif "input_object" in params: kw["input_object"] = face_ids
    if "name" in params: kw["name"] = name
    if "is_perfect_e" in params: kw["is_perfect_e"] = is_pec
    elif "boundary_type" in params:
        kw["boundary_type"] = "PerfectE" if is_pec else "PerfectH"
    fn(**kw)
    print(f"    ✓ Symmetry {'PEC' if is_pec else 'PMC'} → '{name}'")

def _assign_rad_to_faces(hfss, face_ids, name):
    for meth in ("assign_radiation_boundary_to_faces",
                 "create_radiation_boundary_to_faces",
                 "assign_radiation_to_faces"):
        fn = getattr(hfss, meth, None)
        if fn is None: continue
        try:
            fn(face_ids, name=name)
            print(f"    ✓ Radiation via .{meth} on {len(face_ids)} faces")
            return
        except Exception as e:
            print(f"    ⚠ .{meth}: {e}")
    raise RuntimeError("No face-based radiation method worked")

def assign_wave_port(hfss, port_sheet):
    """Half-width port. Integration line INSET from x=0 to avoid sym plane."""
    face_id = port_sheet.faces[0].id
    inset_x = (5.0 * FEED_W / 2.0) * 0.10   # 10% off x=0
    inset_z = SUB_H * 0.02
    p_lo = [inset_x, -SUB_L/2.0, 0.0 + inset_z]
    p_hi = [inset_x, -SUB_L/2.0, SUB_H - inset_z]
    print(f"    int_line: {p_lo} → {p_hi}")
    fn = hfss.wave_port
    sig = inspect.signature(fn); params = set(sig.parameters)
    KW = {"assignment": face_id, "signal": face_id, "reference": None,
          "create_port_sheet": False, "integration_line": [p_lo, p_hi],
          "impedance": 50, "name": "P1", "renormalize": True,
          "deembed": False, "num_modes": 1, "modes": 1, "is_microstrip": True}
    bnd = fn(**{k: v for k, v in KW.items() if k in params})
    if not bnd: raise RuntimeError("wave_port falsy")
    print(f"    ✓ Wave port assigned (x-inset)")
    return getattr(bnd, "name", "P1")

def insert_sphere(hfss, name="FF_Full"):
    fn = hfss.insert_infinite_sphere
    sig = inspect.signature(fn); params = set(sig.parameters)
    KW = {"theta_start": 0, "x_start": 0, "theta_stop": 180, "x_stop": 180,
          "theta_step": THETA_STEP, "x_step": THETA_STEP,
          "phi_start": -180, "y_start": -180, "phi_stop": 180, "y_stop": 180,
          "phi_step": PHI_STEP, "y_step": PHI_STEP,
          "units": "deg", "name": name}
    fn(**{k: v for k, v in KW.items() if k in params})
    print(f"    ✓ FF_Full inserted")


def set_impedance_multiplier(hfss, multiplier=2):
    """
    Set the design-level Port Impedance Multiplier.
    
    Per ANSYS docs (HFSS 2025 R2):
      HFSS → Excitations → Edit Impedance Multiplier
    
    REQUIRED for symmetric (wedge) models so that computed impedances
    and far-field gains correspond to the FULL structure, not just the
    simulated portion. Without this, gain reads ~3 dB low for a
    half-symmetric model.
    
    This is a GLOBAL setting that applies to all ports in the design,
    NOT a per-port property. Hence we call it on the BoundarySetup
    module, not on individual port boundaries.
    """
    print(f"\n    Setting design-level Impedance Multiplier = {multiplier}...")
    
    # The native HFSS scripting call (matches the GUI menu action)
    try:
        boundary_module = hfss.odesign.GetModule("BoundarySetup")
        boundary_module.EditImpedanceMult([
            "NAME:ImpedanceMultData",
            "Impedance Multiplier:=", str(multiplier)
        ])
        print(f"    ✓ Impedance Multiplier = {multiplier} (via EditImpedanceMult)")
        return True
    except Exception as e:
        print(f"    ⚠ EditImpedanceMult failed: {e}")
    
    # Fallback — try alternative arg formats some HFSS versions accept
    for args in (
        [str(multiplier)],
        [float(multiplier)],
        ["NAME:ImpedanceMultData", "Impedance Multiplier:=", float(multiplier)],
    ):
        try:
            hfss.odesign.GetModule("BoundarySetup").EditImpedanceMult(args)
            print(f"    ✓ Impedance Multiplier = {multiplier} (fallback args: {args})")
            return True
        except Exception:
            continue
    
    print(f"    ❌ All API approaches failed.")
    print(f"    ↪ Set manually: HFSS menu → Excitations → Edit Impedance Multiplier → {multiplier}")
    return False
# =============================================================================
def main():
    t0 = time.time()
    print("="*72)
    print(" PHASE 3a v3 — Symmetric, face-classified (your horn pattern)")
    print("="*72)

    hfss = Hfss(
        project=str(PROJECT_DIR / f"{PROJECT_NAME}.aedt"),
        design=DESIGN_NAME, solution_type="Modal",
        version="2025.2", non_graphical=False, new_desktop=True,
        student_version=True,
    )
    hfss.modeler.model_units = "mm"

    # Purge
    try:
        ex = list(hfss.modeler.object_names)
        if ex: hfss.modeler.delete(ex)
    except Exception: pass
    try:
        for b in list(getattr(hfss, "boundaries", []) or []):
            try: hfss.delete_boundary(getattr(b, "name", str(b)))
            except Exception: pass
    except Exception: pass

    # ---- 1. Variables
    print("\n[1/9] Variables...")
    for k, v in {"f0": f"{F0_GHZ}GHz", "patch_W": f"{PATCH_W}mm",
                 "patch_L": f"{PATCH_L}mm", "feed_W": f"{FEED_W}mm",
                 "inset_d": f"{INSET_DEPTH}mm", "inset_g": f"{INSET_GAP}mm"}.items():
        hfss[k] = v

    # ---- 2. Half-model geometry
    print("\n[2/9] Building half-symmetric geometry...")
    hfss.modeler.create_box(origin=[0.0, -SUB_L/2, 0.0],
        sizes=[SUB_W/2, SUB_L, SUB_H], name="Substrate", material="FR4_epoxy")
    hfss.modeler.create_rectangle(orientation="XY",
        origin=[0.0, -SUB_L/2, 0.0], sizes=[SUB_W/2, SUB_L], name="Ground")
    hfss.modeler.create_rectangle(orientation="XY",
        origin=[0.0, -PATCH_L/2, SUB_H], sizes=[PATCH_W/2, PATCH_L], name="Patch")
    hfss.modeler.create_rectangle(orientation="XY",
        origin=[FEED_W/2, -PATCH_L/2, SUB_H],
        sizes=[INSET_GAP, INSET_DEPTH], name="NotchR")
    hfss.modeler.subtract("Patch", ["NotchR"], keep_originals=False)
    hfss.modeler.create_rectangle(orientation="XY",
        origin=[0.0, -SUB_L/2, SUB_H], sizes=[FEED_W/2, FEED_L], name="Feed")
    hfss.modeler.unite(["Patch", "Feed"])
    hfss.assign_perfect_e(["Patch"], name="PEC_PatchFeed")
    hfss.assign_perfect_e(["Ground"], name="PEC_Ground")

    hfss.modeler.create_box(origin=[0.0, -SUB_L/2, -AIR_PAD],
        sizes=[SUB_W/2 + AIR_PAD, SUB_L + AIR_PAD, SUB_H + 2*AIR_PAD],
        name="AirBox", material="air")
    port_sheet = hfss.modeler.create_rectangle(orientation="XZ",
        origin=[0.0, -SUB_L/2, 0.0], sizes=[5*FEED_W/2, 6*SUB_H], name="PortSheet")
    print(f"    ✓ Geometry built")

    # ---- 3-5. THE KEY FIX — face-classified BCs
    print("\n[3/9] Classifying AirBox faces by centroid...")
    faces = classify_airbox_faces(hfss, "AirBox")

    print("\n[4/9] Symmetry PMC on x=0 face ONLY...")
    _assign_sym(hfss, faces["sym_x0"], is_pec=False, name="Sym_PMC_x0")

    print("\n[5/9] Radiation on 5 OUTER faces ONLY (NO overlap)...")
    _assign_rad_to_faces(hfss, faces["radiation"], "Rad_Outer")

    # ---- 6. Wave port + design-level impedance multiplier
    print("\n[6/9] Wave port (x-inset to avoid sym plane)...")
    port_name = assign_wave_port(hfss, port_sheet)
    
    # Per ANSYS docs: half-symmetric (wedge) models require multiplier=2
    # so reported impedances and gain correspond to the full structure.
    set_impedance_multiplier(hfss, multiplier=2)

    # ---- 7. Setup + sphere
    print("\n[7/9] Setup + sphere...")
    setup = hfss.create_setup(name="Setup_FF_Sym")
    setup.props["Frequency"] = f"{F0_GHZ}GHz"
    setup.props["MaximumPasses"] = 12
    setup.props["MinimumPasses"] = 4
    setup.props["MinimumConvergedPasses"] = 2
    setup.props["MaxDeltaS"] = 0.01
    setup.props["BasisOrder"] = 1
    setup.update()
    insert_sphere(hfss, "FF_Full")

    # ---- 8. Validate + review
    print("\n[8/9] Validate...")
    try: hfss.validate_simple()
    except Exception as e: print(f"    ⚠ {e}")
    try:
        hfss.modeler.fit_all()
        hfss.post.export_model_picture(
            full_name=str(PROJECT_DIR / "img" / "geometry_symmetric_fixed.png"),
            width=1920, height=1080)
    except Exception: pass

    print("\n" + "─"*72)
    print("  Verify NO overlap warnings in Message Manager:")
    print("    • Sym_PMC_x0 (1 face)")
    print("    • Rad_Outer  (5 faces)")
    print("─"*72)
    try: input("  ▶ Press Enter to solve... ")
    except KeyboardInterrupt:
        hfss.save_project(); return

    # ---- 9. Solve + extract
    print("\n[9/9] Solving...")
    t_s = time.time()
    hfss.analyze(cores=4, setup="Setup_FF_Sym")
    print(f"    ✓ Solved in {(time.time()-t_s)/60:.2f} min")
    hfss.save_project()

    print("\n  Extracting via dB(GainTotal) [explicit dB unit]...")
    last_adapt = "Setup_FF_Sym : LastAdaptive"
    fn = hfss.post.get_solution_data
    phi_list = np.arange(-180.0, 181.0, PHI_STEP)

    cut0 = fn(expressions=["dB(GainTotal)"], setup_sweep_name=last_adapt,
              context="FF_Full", report_category="Far Fields",
              primary_sweep_variable="Theta",
              variations={"Phi": ["0deg"], "Freq": [f"{F0_GHZ}GHz"]})
    thetas = np.array(cut0.primary_sweep_values, dtype=float)
    print(f"    θ: {len(thetas)} samples [{thetas[0]:.0f},{thetas[-1]:.0f}]°")

    gain_dBi = np.full((len(thetas), len(phi_list)), np.nan)
    gain_dBi[:, np.argmin(np.abs(phi_list))] = _extract(cut0, "dB(GainTotal)")

    success = 1
    for j, ph in enumerate(phi_list):
        if abs(ph) < 1e-6: continue
        try:
            cut = fn(expressions=["dB(GainTotal)"], setup_sweep_name=last_adapt,
                     context="FF_Full", report_category="Far Fields",
                     primary_sweep_variable="Theta",
                     variations={"Phi": [f"{ph:g}deg"], "Freq": [f"{F0_GHZ}GHz"]})
            d = _extract(cut, "dB(GainTotal)")
            if len(d) == len(thetas):
                gain_dBi[:, j] = d
                success += 1
            if (j+1) % 30 == 0:
                print(f"      {j+1}/{len(phi_list)}, {success} OK")
        except Exception: pass

    print(f"\n    ✓ {success}/{len(phi_list)} cuts captured")
    peak = float(np.nanmax(gain_dBi))
    ip, jp = np.unravel_index(np.nanargmax(gain_dBi), gain_dBi.shape)
    print(f"\n📡 Peak: {peak:.2f} dBi at θ={thetas[ip]:.1f}° φ={phi_list[jp]:.1f}°")
    print(f"   Range: [{np.nanmin(gain_dBi):.2f}, {peak:.2f}] dBi")

    np.savez_compressed(PROJECT_DIR / "csv" / "farfield_3d.npz",
        theta_deg=thetas, phi_deg=phi_list, gain_dBi=gain_dBi,
        f0_GHz=F0_GHZ, peak_dBi=peak,
        peak_theta=float(thetas[ip]), peak_phi=float(phi_list[jp]))
    sz = (PROJECT_DIR / "csv" / "farfield_3d.npz").stat().st_size // 1024
    print(f"\n💾 farfield_3d.npz: shape={gain_dBi.shape}, {sz} KB")
    print(f"\n  ✅ Phase 3a v3 done in {(time.time()-t0)/60:.2f} min")

    hfss.save_project()
    hfss.release_desktop(close_projects=False, close_desktop=False)

if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc(); sys.exit(1)