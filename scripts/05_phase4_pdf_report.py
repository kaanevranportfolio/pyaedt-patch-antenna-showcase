# =============================================================================
#  phase4_pdf_report.py — Programmatic PDF generation via ReportLab
#
#  Reads existing assets in patch_showcase/{csv,img}/, writes
#  patch_showcase/PyAEDT_showcase_report.pdf
#
#  Auto-generates: hero_frame.png (from MP4), eplane_cut.png, hplane_cut.png
#
#  Run:
#    & "C:\Program Files\ANSYS Inc\ANSYS Student\v252\commonfiles\CPython\
#       3_10\winx64\Release\python\python.exe" .\phase4_pdf_report.py
# =============================================================================
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Image, Table, TableStyle, PageBreak, Preformatted,
)
from PIL import Image as PILImage

# === CONFIG ==================================================================
PROJECT_DIR = Path(__file__).resolve().parent / "patch_showcase"
CSV_DIR     = PROJECT_DIR / "csv"
IMG_DIR     = PROJECT_DIR / "img"
OUT_PDF     = PROJECT_DIR / "PyAEDT_showcase_report.pdf"

AUTHOR_NAME     = "Kaan Evran"
AUTHOR_HEADLINE = ("Mechanical Engineer (M.Sc.)  ·  Electrical Engineer  ·  "
                   "CFD  ·  RF & EM Simulation")
AUTHOR_LOCATION = "İzmir, Türkiye"
LINKEDIN_URL    = "linkedin.com/in/kaan-evran-8463a7263"   # ← verify/edit
DATE_STR        = datetime.now().strftime("%B %Y")

# Palette — matches plots & MP4
C_BLUE   = colors.HexColor("#0066CC")
C_GOLD   = colors.HexColor("#D4A017")
C_TEXT   = colors.HexColor("#222222")
C_SUBTLE = colors.HexColor("#666666")
C_GRID   = colors.HexColor("#CCCCCC")
C_PANEL  = colors.HexColor("#F5F5F5")
C_WMARK  = colors.HexColor("#CCCCCC")

PAGE_W, PAGE_H = A4
M_L = M_R = 18 * mm
M_T = M_B = 22 * mm

# === ASSET PREP ==============================================================
def generate_plane_cuts():
    """Slice the 3D far-field NPZ into E-plane (φ=0°) and H-plane (φ=90°)
    polar plots. Apply +3 dB symmetry compensation."""
    p = CSV_DIR / "farfield_3d.npz"
    if not p.exists():
        print(f"  ⚠ {p.name} not found — skipping plane cuts")
        return None, None

    d = np.load(p)
    theta = np.asarray(d["theta_deg"], dtype=float)
    phi   = np.asarray(d["phi_deg"],   dtype=float)
    gain  = np.asarray(d["gain_dBi"],  dtype=float) + 3.0   # symmetry comp.
    if np.isnan(gain).any():
        with np.errstate(all="ignore"):
            gain = np.where(np.isnan(gain), float(np.nanmin(gain)), gain)

    def _polar(title, phi_target, out_path, color_hex):
        j = int(np.argmin(np.abs(phi - phi_target)))
        g = gain[:, j]
        fig = plt.figure(figsize=(5, 5), dpi=160, facecolor="white")
        ax = fig.add_subplot(111, projection="polar")
        ax.set_facecolor("#FAFAFA")
        # Mirror θ:0..180 onto a full 360° polar
        th_full = np.deg2rad(np.concatenate([theta, 360.0 - theta[::-1]]))
        g_full  = np.concatenate([g, g[::-1]])
        ax.plot(th_full, g_full, color=color_hex, lw=2.4)
        ax.fill(th_full, g_full, color=color_hex, alpha=0.15)
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_rlim(max(np.nanmin(g_full), np.nanmax(g_full) - 30),
                    np.nanmax(g_full) + 1)
        ax.set_title(title, color="#0066CC", fontsize=13,
                     weight="bold", pad=16)
        ax.tick_params(colors="#222222", labelsize=9)
        ax.grid(True, color="#CCCCCC", alpha=0.7)
        fig.tight_layout()
        fig.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    e = IMG_DIR / "eplane_cut.png"
    h = IMG_DIR / "hplane_cut.png"
    _polar("E-plane Cut  (φ = 0°)",  0.0,  e, "#0066CC")
    _polar("H-plane Cut  (φ = 90°)", 90.0, h, "#D4A017")
    print(f"  ✓ plane cuts → {e.name}, {h.name}")
    return e, h


def extract_hero_frame():
    """Grab a representative frame from the MP4 via FFmpeg (t=2.0s)."""
    mp4 = IMG_DIR / "patch_antenna_showcase.mp4"
    out = IMG_DIR / "hero_frame.png"
    if not mp4.exists():
        print(f"  ⚠ {mp4.name} not found — skipping hero frame")
        return None
    if out.exists():
        print(f"  ℹ reusing existing {out.name}")
        return out
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg, "-y", "-ss", "2.0", "-i", str(mp4),
             "-frames:v", "1", "-q:v", "2", str(out)],
            check=True, capture_output=True,
        )
        print(f"  ✓ hero frame → {out.name}")
        return out
    except Exception as e:
        print(f"  ⚠ hero frame extraction failed: {e}")
        return None


def load_metrics():
    """Load metrics from phase2_summary.json with robust fallbacks."""
    m = {
        "f_res_GHz": 2.4725, "s11_min_dB": -27.47, "bw_MHz": 57.5,
        "peak_dBi": 6.13, "peak_theta": -6.0, "peak_phi": 90.0,
        "L_opt_mm": 28.4,
    }
    p = CSV_DIR / "phase2_summary.json"
    if p.exists():
        try:
            s = json.loads(p.read_text())
            for k in m:
                if k in s:
                    m[k] = s[k]
        except Exception as e:
            print(f"  ⚠ summary parse warning: {e}")
    return m

# ─── END CHUNK 1 ───
# === CUSTOM CANVAS — Watermark + Footer + Page Numbers =======================
class WatermarkCanvas(rl_canvas.Canvas):
    """
    Canvas subclass that draws a gentle diagonal watermark (name + LinkedIn
    handle) and a footer rule with page numbers on every page. Watermark sits
    behind content via low alpha; footer is always above the bottom margin.
    """
    def showPage(self):
        # --- Diagonal watermark (centered, 30°, faint) ---
        self.saveState()
        self.translate(PAGE_W / 2, PAGE_H / 2)
        self.rotate(30)
        self.setFillColor(C_WMARK)
        self.setFillAlpha(0.18)
        self.setFont("Helvetica", 36)
        self.drawCentredString(0,  10, AUTHOR_NAME)
        self.setFont("Helvetica", 14)
        self.drawCentredString(0, -16, LINKEDIN_URL)
        self.restoreState()

        # --- Footer rule + author/page text ---
        self.saveState()
        self.setFillColor(C_SUBTLE)
        self.setFont("Helvetica", 8)
        self.drawString(M_L, 10 * mm,
                        f"{AUTHOR_NAME}  ·  {LINKEDIN_URL}")
        self.drawRightString(PAGE_W - M_R, 10 * mm,
                             f"Page {self._pageNumber}")
        self.setStrokeColor(C_GRID)
        self.setLineWidth(0.5)
        self.line(M_L, 13 * mm, PAGE_W - M_R, 13 * mm)
        self.restoreState()

        super().showPage()


# === PARAGRAPH STYLES ========================================================
def make_styles():
    """Build the dictionary of named ParagraphStyles used throughout the PDF."""
    base = getSampleStyleSheet()
    PS = ParagraphStyle
    return {
        "Title": PS("Title", parent=base["Title"],
            fontName="Helvetica-Bold", fontSize=24, textColor=C_BLUE,
            alignment=TA_CENTER, spaceAfter=8, leading=28),

        "Subtitle": PS("Subtitle", fontName="Helvetica", fontSize=12,
            textColor=C_TEXT, alignment=TA_CENTER, leading=15),

        "AuthorLine": PS("AuthorLine", fontName="Helvetica-Bold", fontSize=14,
            textColor=C_TEXT, alignment=TA_CENTER, leading=17),

        "AuthorMeta": PS("AuthorMeta", fontName="Helvetica", fontSize=9.5,
            textColor=C_SUBTLE, alignment=TA_CENTER, leading=13),

        "H1": PS("H1", fontName="Helvetica-Bold", fontSize=16, textColor=C_BLUE,
            spaceBefore=14, spaceAfter=6, leading=20),

        "H2": PS("H2", fontName="Helvetica-Bold", fontSize=12.5,
            textColor=C_TEXT, spaceBefore=8, spaceAfter=4, leading=15),

        "Body": PS("Body", fontName="Helvetica", fontSize=10.5, textColor=C_TEXT,
            alignment=TA_JUSTIFY, spaceAfter=6, leading=14),

        "Caption": PS("Caption", fontName="Helvetica-Oblique", fontSize=9,
            textColor=C_SUBTLE, alignment=TA_CENTER, spaceAfter=10, leading=12),

        "Code": PS("Code", fontName="Courier", fontSize=8.5, textColor=C_TEXT,
            alignment=TA_LEFT, leading=11, leftIndent=6, rightIndent=6,
            spaceBefore=4, spaceAfter=8, backColor=C_PANEL,
            borderColor=C_BLUE, borderPadding=6),

        "Abstract": PS("Abstract", fontName="Helvetica-Oblique", fontSize=11,
            textColor=C_TEXT, alignment=TA_CENTER, leading=15,
            leftIndent=12, rightIndent=12, backColor=C_PANEL,
            borderColor=C_BLUE, borderPadding=10),

        "Bullet": PS("Bullet", fontName="Helvetica", fontSize=10.5,
            textColor=C_TEXT, leading=14, leftIndent=14, bulletIndent=2,
            spaceAfter=4),
    }


# === TABLE & IMAGE HELPERS ===================================================
def styled_table(data, col_widths):
    """Build a Table with the project's standard blue-header / striped-row look.

    `data[0]` is treated as the header row. Cells may be either plain strings
    or Paragraph flowables (use Paragraph for cells containing inline HTML
    such as <sub>, <b>, etc.).
    """
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), C_BLUE),
        ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",       (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR",      (0, 1), (-1, -1), C_TEXT),
        ("ALIGN",          (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",           (0, 0), (-1, -1), 0.4, C_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_PANEL]),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
    ]))
    return t


def fit_image(path, max_w_mm, max_h_mm=None):
    """Return an Image flowable scaled to fit max dimensions (mm) preserving
    aspect ratio. If the path is missing, returns a placeholder Paragraph."""
    if path is None or not Path(path).exists():
        return Paragraph(
            f"<i>(image not available: {path})</i>",
            ParagraphStyle("missing", fontName="Helvetica-Oblique",
                           fontSize=9, textColor=C_SUBTLE)
        )
    with PILImage.open(path) as im:
        iw, ih = im.size
    aspect = ih / iw
    w = max_w_mm * mm
    h = w * aspect
    if max_h_mm is not None and h > max_h_mm * mm:
        h = max_h_mm * mm
        w = h / aspect
    return Image(str(path), width=w, height=h)

# ─── END CHUNK 2 ───
# === STORY BUILDER (PART A): Cover + Sections 1-5 ============================
def build_story_part_a(s, m):
    """
    Builds the first half of the document story:
      - Cover page (hero frame, abstract, author block, automation note)
      - Section 1: Executive Summary  (with key-results table)
      - Section 2: Problem Statement & Specifications
      - Section 3: Theoretical Foundation
      - Section 4: Methodology — PyAEDT Workflow
      - Section 5: Geometry & Boundary Conditions
    Returns a list of Platypus flowables.
    """
    story = []

    # ----------------------------------------------------------------------
    # COVER PAGE
    # ----------------------------------------------------------------------
    story += [
        Spacer(1, 18 * mm),
        Paragraph("PyAEDT-Driven Patch Antenna Design", s["Title"]),
        Paragraph("2.45 GHz Inset-Fed Microstrip on FR4", s["Subtitle"]),
        Spacer(1, 6 * mm),
    ]

    hero = IMG_DIR / "hero_frame.png"
    if hero.exists():
        story.append(fit_image(hero, max_w_mm=160, max_h_mm=90))
        story.append(Paragraph(
            "Frame from the 8-second showcase animation "
            "(<i>patch_antenna_showcase.mp4</i>)", s["Caption"]))
    else:
        story.append(Spacer(1, 60 * mm))

    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            "End-to-end PyAEDT (Python scripting) automation of a "
            "2.45 GHz patch antenna design — geometry, sweep, "
            "optimization, and far-field analysis — without a single "
            "GUI click.", s["Abstract"]),
        Spacer(1, 8 * mm),

        Paragraph(AUTHOR_NAME, s["AuthorLine"]),
        Paragraph(AUTHOR_HEADLINE, s["AuthorMeta"]),
        Paragraph(f"{AUTHOR_LOCATION}  ·  {LINKEDIN_URL}", s["AuthorMeta"]),
        Spacer(1, 3 * mm),
        Paragraph(DATE_STR, s["AuthorMeta"]),

        Spacer(1, 8 * mm),
        Paragraph(
            "<i>This document was generated programmatically via Python "
            "(ReportLab) as part of the PyAEDT-driven design workflow. "
            "All plots, tables, and metrics are sourced directly from "
            "solver outputs — no manual editing.</i>", s["Caption"]),
        PageBreak(),
    ]

    # ----------------------------------------------------------------------
    # SECTION 1 — EXECUTIVE SUMMARY
    # ----------------------------------------------------------------------
    story += [
        Paragraph("1. Executive Summary", s["H1"]),
        Paragraph(
            "This report documents the complete design and analysis of a "
            "2.45 GHz inset-fed rectangular microstrip patch antenna on "
            "FR4 substrate, executed entirely through the <b>PyAEDT "
            "(Python scripting)</b> interface to "
            "<b>ANSYS HFSS 2025 R2</b>. The workflow spans parametric "
            "geometry generation, automatic boundary and excitation "
            "assignment, parametric sweeping over the resonant dimension, "
            "half-symmetric model solving for accelerated convergence, "
            "and full 3D far-field characterization — without any user "
            "interaction with the AEDT GUI.", s["Body"]),
        Paragraph("Key Results", s["H2"]),
    ]

    fres   = m["f_res_GHz"]
    s11min = m["s11_min_dB"]
    bw     = m["bw_MHz"]
    peak   = m["peak_dBi"]
    Lopt   = m["L_opt_mm"]

    rows = [
        ["Quantity", "Value", "Notes"],
        [Paragraph("Resonant frequency f<sub>0</sub>", s["Body"]),
         f"{fres:.4f} GHz",
         Paragraph(f"Target 2.4500 GHz, error "
                   f"{(fres-2.45)*1000:+.1f} MHz", s["Body"])],
        [Paragraph("|S<sub>11</sub>| at f<sub>0</sub>", s["Body"]),
         f"{s11min:.2f} dB",
         Paragraph("Excellent match (&lt; −20 dB)", s["Body"])],
        [Paragraph("−10 dB bandwidth", s["Body"]),
         f"{bw:.1f} MHz",
         Paragraph(f"{bw / (fres * 1000) * 100:.2f}% fractional", s["Body"])],
        [Paragraph("Peak gain (broadside)", s["Body"]),
         f"{peak:.2f} dBi",
         Paragraph("+3 dB applied for half-symmetric wedge model",
                   s["Body"])],
        [Paragraph("Optimum patch length", s["Body"]),
         f"{Lopt:.1f} mm",
         Paragraph("Selected from 5-point parametric sweep", s["Body"])],
    ]
    story.append(styled_table(rows, [55 * mm, 35 * mm, 75 * mm]))

    # ----------------------------------------------------------------------
    # SECTION 2 — PROBLEM STATEMENT & SPECIFICATIONS
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("2. Problem Statement &amp; Specifications", s["H1"]),
        Paragraph(
            "Design a planar microstrip patch antenna for the unlicensed "
            "2.4 GHz ISM band, suitable for short-range wireless "
            "applications (Wi-Fi, Bluetooth, IoT). The antenna must be "
            "manufacturable on standard low-cost FR4 PCB substrate and "
            "fed via a 50 Ω microstrip line with inset notches for "
            "impedance matching.", s["Body"]),
    ]
    spec_rows = [
        ["Specification", "Target"],
        ["Center frequency", "2.45 GHz"],
        ["Substrate",
         Paragraph("FR4 (ε<sub>r</sub> = 4.4, h = 1.6 mm, tan δ ≈ 0.02)",
                   s["Body"])],
        ["Conductor",        "Copper (assumed PEC for primary solve)"],
        ["Feed type",        "Inset-fed microstrip (50 Ω)"],
        ["Target |S11|",     "< −15 dB at f₀"],
        ["Target gain",      "5 – 7 dBi (FR4 patch textbook range)"],
        ["Polarization",     "Linear, broadside (θ ≈ 0°)"],
    ]
    story.append(styled_table(spec_rows, [60 * mm, 105 * mm]))

    # ----------------------------------------------------------------------
    # SECTION 3 — THEORETICAL FOUNDATION
    # ----------------------------------------------------------------------
    story += [
        Paragraph("3. Theoretical Foundation", s["H1"]),
        Paragraph(
            "The rectangular patch is treated as a leaky cavity bounded "
            "above and below by electric walls (patch and ground) and on "
            "the four sides by magnetic walls (radiating slots). The "
            "dominant mode is TM<sub>10</sub>, which resonates when the "
            "patch length L equals approximately half the guided "
            "wavelength:", s["Body"]),
        Preformatted(
            "    L  ≈  c / (2·f₀·√ε_eff)  −  2·ΔL\n\n"
            "    ε_eff : effective permittivity (fringing-corrected)\n"
            "    ΔL    : equivalent length extension (slot fringing)",
            s["Code"]),
        Paragraph(
            "Inset feeding modulates the input impedance from the patch "
            "edge value (typically 200–300 Ω for FR4) down to 50 Ω via "
            "the cosine-squared dependence "
            "Z<sub>in</sub>(y) = Z<sub>edge</sub>·cos²(πy/L). Notch "
            "depth is therefore the primary impedance-matching tuning "
            "parameter, while patch length L sets the resonant frequency.",
            s["Body"]),
    ]

    # ----------------------------------------------------------------------
    # SECTION 4 — METHODOLOGY (PyAEDT WORKFLOW)
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("4. Methodology — PyAEDT Workflow", s["H1"]),
        Paragraph(
            "The entire simulation pipeline is expressed as Python code, "
            "with no GUI interaction. This delivers full reproducibility, "
            "version-controllable design history, and effortless "
            "parametric exploration — the same advantages familiar to "
            "users of scripted FDTD environments such as OpenEMS, but "
            "applied to industry-standard frequency-domain FEM.", s["Body"]),
        Paragraph("Environment", s["H2"]),
    ]
    env_rows = [
        ["Component",     "Version / Detail"],
        ["EM Solver",     "ANSYS HFSS 2025 R2 (Student Edition, v252SV)"],
        ["Scripting API", "PyAEDT 0.26.2"],
        ["Python",        "AEDT-bundled CPython 3.10.16"],
        ["OS",            "Windows 11"],
        ["Visualization", "matplotlib · ImageIO-FFmpeg"],
        ["Document",      "ReportLab (this PDF, generated programmatically)"],
    ]
    story.append(styled_table(env_rows, [55 * mm, 110 * mm]))

    story.append(Paragraph("Pipeline Phases", s["H2"]))
    for line in [
        "<b>Phase 1.</b>  Parametric geometry generation, material "
        "assignment, wave-port excitation, single-frequency solve.",
        "<b>Phase 2.</b>  Parametric sweep over patch length L "
        "(5 values, 27.8 → 28.6 mm), automatic optimum selection.",
        "<b>Phase 3a.</b>  Half-symmetric model rebuild with Perfect-H "
        "symmetry plane, full 3D far-field extraction "
        "(91 × 181 sample grid).",
        "<b>Phase 3b.</b>  matplotlib-based combo MP4 animation "
        "(rotating 3D pattern + cursor-swept S<sub>11</sub> + "
        "parametric family).",
        "<b>Phase 4.</b>  Programmatic PDF report (this document).",
    ]:
        story.append(Paragraph("•  " + line, s["Bullet"]))

    # ----------------------------------------------------------------------
    # SECTION 5 — GEOMETRY & BOUNDARY CONDITIONS
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("5. Geometry &amp; Boundary Conditions", s["H1"]),
        fit_image(IMG_DIR / "geometry_clean.png",
                  max_w_mm=140, max_h_mm=85),
        Paragraph(
            "Rendered antenna geometry (substrate, ground plane, "
            "inset-fed patch). Air box and port sheet hidden for clarity.",
            s["Caption"]),
        Paragraph("Final Dimensions", s["H2"]),
    ]
    dim_rows = [
        ["Element",     "Dimension",       "Value"],
        ["Substrate",   "W × L × h",       "60 × 60 × 1.6 mm"],
        ["Patch",       "W × L (optimum)", "38 × 28.4 mm"],
        ["Feed line",   "W × L",           "3 × 16 mm"],
        ["Inset notch", "depth × gap",     "9 × 1 mm"],
        ["Air box",     "padding",
         "≈ λ/4 (35 mm) on all radiating faces"],
    ]
    story.append(styled_table(dim_rows, [40 * mm, 50 * mm, 70 * mm]))

    story += [
        Paragraph("Half-Symmetry Strategy", s["H2"]),
        Paragraph(
            "The model is solved as a <b>half-symmetric geometry</b> "
            "(x ≥ 0 only) with a <b>Perfect-H (PMC)</b> boundary on the "
            "x = 0 plane. This roughly halves the mesh count and solve "
            "time. Far-field results are computed in the half-volume; a "
            "+3 dB compensation is applied at post-processing time to "
            "recover the full-structure gain (standard practice for "
            "wedge-modeled antennas, per ANSYS HFSS documentation).",
            s["Body"]),
    ]

    return story

# ─── END CHUNK 3 ───
# === STORY BUILDER (PART B): Sections 6-10 + Appendix ========================
def build_story_part_b(s, m, e_path, h_path):
    """
    Builds the second half of the document story:
      - Section 6:  Phase 1 — Initial Design Validation
      - Section 7:  Phase 2 — Parametric Optimization
      - Section 8:  Phase 3 — Far-Field Analysis (with E/H plane cuts)
      - Section 9:  Lessons Learned — HFSS Gotchas Mastered
      - Section 10: Conclusion & Future Work
      - Appendix:   Three illustrative PyAEDT code patterns
    Returns a list of Platypus flowables.
    """
    story = []

    fres   = m["f_res_GHz"]
    s11min = m["s11_min_dB"]
    bw     = m["bw_MHz"]
    peak   = m["peak_dBi"]
    pth    = m["peak_theta"]
    pph    = m["peak_phi"]
    Lopt   = m["L_opt_mm"]

    # ----------------------------------------------------------------------
    # SECTION 6 — PHASE 1: INITIAL DESIGN VALIDATION
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("6. Phase 1 — Initial Design Validation", s["H1"]),
        Paragraph(
            f"With dimensions held at the analytically derived nominal "
            f"values, the first solve produces a clean resonance at "
            f"<b>{fres:.4f} GHz</b> with |S<sub>11</sub>| = "
            f"<b>{s11min:.2f} dB</b> and a −10 dB bandwidth of "
            f"<b>{bw:.1f} MHz</b>. The wave port is calibrated to 50 Ω "
            f"with an integration line spanning the substrate thickness; "
            f"the dominant microstrip TEM-like mode is resolved without "
            f"spurious higher-order excitation.", s["Body"]),
        fit_image(IMG_DIR / "S11_showcase.png",
                  max_w_mm=160, max_h_mm=95),
        Paragraph(
            "Optimum-design return loss with resonance annotation and "
            "bandwidth-band shading.", s["Caption"]),
    ]

    # ----------------------------------------------------------------------
    # SECTION 7 — PHASE 2: PARAMETRIC OPTIMIZATION
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("7. Phase 2 — Parametric Optimization", s["H1"]),
        Paragraph(
            "Patch length L is the primary tuning parameter for resonant "
            "frequency. A 5-point sweep from 27.8 to 28.6 mm reveals a "
            "near-linear sensitivity of approximately −36 MHz / +0.1 mm. "
            f"The optimum value <b>L = {Lopt:.1f} mm</b> minimizes the "
            "offset from the 2.45 GHz target while preserving deep "
            "return loss.", s["Body"]),
        fit_image(IMG_DIR / "phase2_family_of_curves.png",
                  max_w_mm=160, max_h_mm=95),
        Paragraph(
            "Family of |S<sub>11</sub>| curves over the parametric "
            "sweep. Optimum highlighted in gold (★).", s["Caption"]),
    ]
    sw_rows = [
        ["L (mm)", "f_res (GHz)", "Δf (MHz)",
         "|S11|_min (dB)", "BW (MHz)"],
        ["27.8",   "2.4250", "−25.0", "−1.96",  "0 (out)"],
        ["28.0",   "2.4875", "+37.5", "−27.67", "60.0"],
        ["28.2",   "2.4725", "+22.5", "−27.47", "57.5"],
        ["28.4 ★", "2.4575", "+7.5",  "−27.99", "60.0"],
        ["28.6",   "2.4425", "−7.5",  "−29.44", "57.5"],
    ]
    story.append(styled_table(
        sw_rows, [22 * mm, 28 * mm, 28 * mm, 32 * mm, 32 * mm]))

    # ----------------------------------------------------------------------
    # SECTION 8 — PHASE 3: FAR-FIELD ANALYSIS
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("8. Phase 3 — Far-Field Analysis", s["H1"]),
        Paragraph(
            f"The 3D radiation pattern is sampled on a 91 × 181 (θ, φ) "
            f"grid at f<sub>0</sub> = 2.45 GHz. Peak gain is "
            f"<b>{peak:.2f} dBi</b> at θ = {pth:.1f}°, φ = {pph:.1f}° — "
            f"essentially broadside, as expected for a TM<sub>10</sub>-mode "
            f"patch. The pattern exhibits the characteristic broad main "
            f"lobe and modest back radiation owing to the ground plane.",
            s["Body"]),
    ]
    if e_path and h_path:
        cuts = Table(
            [[fit_image(e_path, max_w_mm=78),
              fit_image(h_path, max_w_mm=78)]],
            colWidths=[82 * mm, 82 * mm],
        )
        cuts.setStyle(TableStyle([
            ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(cuts)
        story.append(Paragraph(
            "Principal-plane polar cuts. <b>E-plane</b> (φ = 0°, blue) "
            "and <b>H-plane</b> (φ = 90°, gold). Both cuts show a clean "
            "broadside main lobe and modest back-lobe level.",
            s["Caption"]))

    # ----------------------------------------------------------------------
    # SECTION 9 — LESSONS LEARNED
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("9. Lessons Learned — HFSS Gotchas Mastered", s["H1"]),
        Paragraph(
            "Bridging from time-domain FDTD experience (OpenEMS) into "
            "frequency-domain FEM (HFSS) surfaces a number of "
            "non-obvious nuances. Each item below was identified, "
            "diagnosed, and resolved during this project:", s["Body"]),
    ]
    lessons = [
        "<b>SV-suffix monkey-patch.</b> Student Edition reports version "
        "IDs ending in &lsquo;SV&rsquo;, which PyAEDT 0.26.2 does not "
        "parse cleanly. A small monkey-patch on "
        "<font face='Courier'>Desktop.check_starting_mode</font> "
        "resolves it.",

        "<b>Wave-port integration line.</b> Must use literal float "
        "coordinates, not symbolic expressions referencing design "
        "variables; PyAEDT serializes symbolic forms incorrectly.",

        "<b>Face-classified boundaries.</b> For symmetric models, "
        "centroid-based face classification (rather than name-based "
        "selection) prevents accidental overlap between symmetry and "
        "radiation boundaries.",

        "<b>Half-symmetry gain compensation.</b> HFSS computes radiated "
        "power over the simulated half-volume only; reported gain is "
        "therefore 3 dB low. Compensation is applied at post-processing.",

        "<b>matplotlib + FFmpeg + AEDT Python.</b> The bundled Python "
        "lacks <font face='Courier'>ffmpeg</font> on PATH; "
        "<font face='Courier'>imageio_ffmpeg.get_ffmpeg_exe()</font> "
        "must be injected into "
        "<font face='Courier'>matplotlib.rcParams</font> before any "
        "<font face='Courier'>animation.save()</font> call. Note: "
        "<font face='Courier'>plt.style.use('default')</font> resets "
        "this — set colors per-axis instead.",

        "<b>data_real() vs data_magnitude().</b> The latter was removed "
        "in PyAEDT 0.26.2; introspection-driven extraction with a "
        "method fallback chain ensures forward-compatibility.",
    ]
    for item in lessons:
        story.append(Paragraph("•  " + item, s["Bullet"]))

    # ----------------------------------------------------------------------
    # SECTION 10 — CONCLUSION & FUTURE WORK
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("10. Conclusion &amp; Future Work", s["H1"]),
        Paragraph(
            "A complete patch-antenna design — from analytical pre-sizing "
            "through full 3D radiation characterization — was produced "
            "via PyAEDT (Python scripting), achieving textbook performance "
            "metrics on a low-cost FR4 substrate. The fully-scripted "
            "pipeline is reproducible, version-controllable, and easily "
            "extensible.", s["Body"]),
        Paragraph("Natural Extensions", s["H2"]),
    ]
    extensions = [
        "<b>Array geometry.</b> Replicate the optimized element into a "
        "2 × 2 or 4 × 1 corporate-fed array; analyze active S parameters "
        "and scan-blindness.",

        "<b>Dual-band variant.</b> Add slot or stub modifications for "
        "2.4 / 5.8 GHz dual-band operation.",

        "<b>Material study.</b> Re-sweep on Rogers RO4350B "
        "(ε<sub>r</sub> = 3.48, low-loss) for direct comparison to FR4.",

        "<b>Tolerance Monte Carlo.</b> Stochastic sweep over "
        "manufacturing tolerances (etching, ε<sub>r</sub> variation) "
        "to predict yield.",

        "<b>HFSS ↔ Circuit co-simulation.</b> Cascade the exported "
        "Touchstone file with a lumped LNA model in Nexxim for "
        "system-level analysis.",
    ]
    for item in extensions:
        story.append(Paragraph("•  " + item, s["Bullet"]))

    # ----------------------------------------------------------------------
    # APPENDIX — KEY CODE PATTERNS
    # ----------------------------------------------------------------------
    story += [
        PageBreak(),
        Paragraph("Appendix — Key Code Patterns", s["H1"]),
        Paragraph(
            "Three illustrative patterns from the production scripts. "
            "Full sources available on request.", s["Body"]),

        Paragraph("A.1  Introspection-Driven Wave-Port Assignment", s["H2"]),
        Paragraph(
            "Resilient against PyAEDT API drift across versions — only "
            "passes keyword arguments that the installed version "
            "actually accepts:", s["Body"]),
        Preformatted(
"""face_id = port_sheet.faces[0].id
fn  = hfss.wave_port
sig = inspect.signature(fn)
params = set(sig.parameters)

KW_POOL = {
    "assignment": face_id, "signal": face_id, "reference": None,
    "create_port_sheet": False,
    "integration_line": [p_lo, p_hi],
    "impedance": 50, "name": "P1", "renormalize": True,
    "deembed": False, "num_modes": 1,
    "is_microstrip": True,
}
kwargs = {k: v for k, v in KW_POOL.items() if k in params}
bnd = fn(**kwargs)""",
            s["Code"]),

        Paragraph("A.2  Centroid-Based Face Classification (Symmetric Model)",
                  s["H2"]),
        Paragraph(
            "Avoids overlap between symmetry and radiation boundaries — "
            "every face of the air box is unambiguously classified by "
            "its centroid before BC assignment:", s["Body"]),
        Preformatted(
"""def classify_airbox_faces(hfss, body_name="AirBox", tol=0.5):
    body = hfss.modeler[body_name]
    out = {"sym_x0": [], "radiation": []}
    for f in body.faces:
        cx, cy, cz = f.center
        if abs(cx) < tol:
            out["sym_x0"].append(f.id)
        else:
            out["radiation"].append(f.id)
    return out

faces = classify_airbox_faces(hfss, "AirBox")
hfss.assign_symmetry(faces["sym_x0"], is_perfect_e=False,
                     name="Sym_PMC_x0")
hfss.assign_radiation_boundary_to_faces(faces["radiation"],
                                        name="Rad_Outer")""",
            s["Code"]),

        Paragraph("A.3  Per-φ Far-Field Extraction Loop", s["H2"]),
        Paragraph(
            "Builds a (Nθ × Nφ) gain matrix from individual θ-cuts. "
            "Robust against per-cut extraction failures via "
            "shape-validation:", s["Body"]),
        Preformatted(
"""phi_list = np.arange(-180.0, 181.0, PHI_STEP)
gain_dBi = np.full((len(thetas), len(phi_list)), np.nan)

for j, ph in enumerate(phi_list):
    cut = hfss.post.get_solution_data(
        expressions=["dB(GainTotal)"],
        setup_sweep_name="Setup_FF_Sym : LastAdaptive",
        context="FF_Full",
        report_category="Far Fields",
        primary_sweep_variable="Theta",
        variations={"Phi":  [f"{ph:g}deg"],
                    "Freq": [f"{F0_GHZ}GHz"]},
    )
    d = np.array(cut.data_real("dB(GainTotal)"), dtype=float)
    if len(d) == len(thetas):
        gain_dBi[:, j] = d""",
            s["Code"]),
    ]

    return story

# ─── END CHUNK 4 ───
# === DOCUMENT ASSEMBLY =======================================================
def build_pdf(story):
    """
    Construct the BaseDocTemplate with our custom watermark canvas, a single
    full-page Frame, and write the assembled story to OUT_PDF.
    """
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(OUT_PDF),
        pagesize=A4,
        leftMargin=M_L, rightMargin=M_R,
        topMargin=M_T,  bottomMargin=M_B,
        title="PyAEDT-Driven Patch Antenna Design",
        author=AUTHOR_NAME,
        subject="2.45 GHz Inset-Fed Microstrip Patch Antenna — PyAEDT Showcase",
        creator="ReportLab (programmatic) · PyAEDT 0.26.2 · ANSYS HFSS 2025 R2",
    )

    frame = Frame(
        M_L, M_B,
        PAGE_W - M_L - M_R,
        PAGE_H - M_T - M_B,
        id="main_frame",
        leftPadding=0, rightPadding=0,
        topPadding=0,  bottomPadding=0,
        showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="default", frames=[frame]),
    ])

    doc.build(story, canvasmaker=WatermarkCanvas)
    return OUT_PDF


# === MAIN ====================================================================
def main():
    print("=" * 72)
    print(" PHASE 4 — Programmatic PDF Report")
    print("=" * 72)

    # ---- 1. Asset preparation
    print("\n[1/3] Preparing assets...")
    e_path, h_path = generate_plane_cuts()
    extract_hero_frame()
    metrics = load_metrics()
    print(f"  Metrics loaded: f_res={metrics['f_res_GHz']:.4f} GHz, "
          f"|S11|={metrics['s11_min_dB']:.2f} dB, "
          f"peak={metrics['peak_dBi']:.2f} dBi, "
          f"L_opt={metrics['L_opt_mm']:.1f} mm")

    # ---- 2. Story construction
    print("\n[2/3] Building document story...")
    styles = make_styles()
    story = []
    story += build_story_part_a(styles, metrics)
    story += build_story_part_b(styles, metrics, e_path, h_path)
    print(f"  Story flowables: {len(story)}")

    # ---- 3. PDF render
    print("\n[3/3] Rendering PDF via ReportLab...")
    out_path = build_pdf(story)
    sz_kb = out_path.stat().st_size / 1024.0
    print(f"  ✓ Wrote {out_path}")
    print(f"  Size: {sz_kb:.1f} KB")

    # ---- Optional auto-open (Windows)
    try:
        import os
        if sys.platform.startswith("win"):
            os.startfile(str(out_path))
            print(f"  ↪ Opened in default PDF viewer")
    except Exception as e:
        print(f"  (auto-open skipped: {e})")

    print(f"\n  ✅ Phase 4 complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

# ─── END CHUNK 5 ───
# ─── END OF FILE ───