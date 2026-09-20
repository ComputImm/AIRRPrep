"""
Render the SVG figures to tightly cropped vector PDFs (and 300-dpi-equivalent
PNG previews) with Microsoft Edge in headless mode.

    python render_figures.py

figure1_workflow.svg -> figure1_workflow.pdf   (main text, Figure 1)
figure2_bulk_lanes.svg -> figure2_bulk_lanes.pdf (Supplementary Figure S4)

Each SVG is placed in a one-page HTML document whose @page size equals the
SVG viewBox, so the PDF has no margins; `currentColor` is resolved to black.
"""

import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
FIGURES = ["figure1_workflow", "figure2_bulk_lanes"]


def render(name: str) -> None:
    svg = (HERE / f"{name}.svg").read_text(encoding="utf-8")
    w, h = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    html = HERE / f"_{name}.html"
    html.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {w}px {h}px; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: #fff; color: #000; }}
svg {{ display: block; width: {w}px; height: {h}px; font-family: Arial, Helvetica, sans-serif; }}
</style></head><body>{svg}</body></html>""", encoding="utf-8")
    pdf = HERE / f"{name}.pdf"
    png = HERE / f"{name}_preview.png"
    common = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
              "--run-all-compositor-stages-before-draw", "--hide-scrollbars"]
    subprocess.run(common + ["--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri()],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(common + [f"--window-size={int(w)},{int(h)}", "--force-device-scale-factor=3",
                             f"--screenshot={png}", html.as_uri()],
                   check=True, capture_output=True, timeout=120)
    html.unlink()
    print(name, "->", pdf.name, pdf.stat().st_size, "bytes;", png.name)


if __name__ == "__main__":
    for figure in FIGURES:
        render(figure)
