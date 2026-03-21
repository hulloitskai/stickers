#!/usr/bin/env python3

"""
cutcontour.py - Generate CutContour PDF for Roland VersaWorks

Extracts path elements from an SVG and creates a PDF with those
paths drawn using a "CutContour" spot color separation, which VersaWorks
recognizes for contour cutting.
"""

import re
import math
import base64
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
import sys
from typing import Annotated
import xml.etree.ElementTree as ET
import typer
from svgpathtools import parse_path, Line, CubicBezier, QuadraticBezier, Arc
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import CMYKColorSep
from reportlab.lib.utils import ImageReader


SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK_NS = "{http://www.w3.org/1999/xlink}"
IDENTITY = (1, 0, 0, 1, 0, 0)
SVG_PX_TO_PT = 72 / 96  # Inkscape 96 DPI -> PDF 72 DPI


def compose(m1, m2):
    """Compose two affine transforms (a, b, c, d, e, f)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def parse_transform(s):
    """Parse SVG transform string into affine matrix tuple."""
    if not s:
        return IDENTITY
    result = IDENTITY
    for match in re.finditer(r"(matrix|translate|scale|rotate)\s*\(([^)]+)\)", s):
        func, args_str = match.group(1), match.group(2)
        args = [float(x) for x in re.split(r"[\s,]+", args_str.strip())]
        if func == "matrix" and len(args) == 6:
            m = tuple(args)
        elif func == "translate":
            m = (1, 0, 0, 1, args[0], args[1] if len(args) > 1 else 0)
        elif func == "scale":
            sx = args[0]
            sy = args[1] if len(args) > 1 else sx
            m = (sx, 0, 0, sy, 0, 0)
        elif func == "rotate":
            a = math.radians(args[0])
            ca, sa = math.cos(a), math.sin(a)
            if len(args) == 3:
                cx, cy = args[1], args[2]
                m = (ca, sa, -sa, ca, cx - ca * cx + sa * cy, cy - sa * cx - ca * cy)
            else:
                m = (ca, sa, -sa, ca, 0, 0)
        else:
            continue
        result = compose(result, m)
    return result


def get_ancestor_transform(element, parent_map):
    """Accumulate transforms from root down to element."""
    chain = []
    el = element
    while el in parent_map:
        el = parent_map[el]
        t = parse_transform(el.get("transform"))
        if t != IDENTITY:
            chain.append(t)
    # Compose from root down
    result = IDENTITY
    for t in reversed(chain):
        result = compose(result, t)
    # Include element's own transform
    own = parse_transform(element.get("transform"))
    if own != IDENTITY:
        result = compose(result, own)
    return result


def arc_to_beziers(arc):
    """Convert an SVG Arc segment to a list of cubic bezier tuples (p0, c1, c2, p1).

    Uses svgpathtools' center parameterization (arc.center, arc.theta, arc.delta)
    and splits into <=90-degree segments approximated by cubic beziers.
    """
    rx, ry = arc.radius.real, arc.radius.imag
    phi = math.radians(arc.rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    cx, cy = arc.center.real, arc.center.imag

    # svgpathtools gives theta/delta in degrees
    theta1 = math.radians(arc.theta)
    dtheta = math.radians(arc.delta)

    # Split into segments of <= 90 degrees
    n_segs = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    seg_angle = dtheta / n_segs

    # Magic number for cubic bezier arc approximation
    alpha = 4.0 / 3.0 * math.tan(seg_angle / 4)

    def to_world(pt):
        """Rotate by phi and translate to center."""
        x = cos_phi * pt.real - sin_phi * pt.imag + cx
        y = sin_phi * pt.real + cos_phi * pt.imag + cy
        return complex(x, y)

    beziers = []
    for i in range(n_segs):
        a1 = theta1 + i * seg_angle
        a2 = a1 + seg_angle

        cos1, sin1 = math.cos(a1), math.sin(a1)
        cos2, sin2 = math.cos(a2), math.sin(a2)

        # Points on the ellipse in rotated frame
        ep1 = complex(rx * cos1, ry * sin1)
        ep2 = complex(rx * cos2, ry * sin2)
        c1 = complex(rx * (cos1 - alpha * sin1), ry * (sin1 + alpha * cos1))
        c2 = complex(rx * (cos2 + alpha * sin2), ry * (sin2 - alpha * cos2))

        beziers.append((to_world(ep1), to_world(c1), to_world(c2), to_world(ep2)))

    return beziers


def draw_path_on_canvas(canvas, d_string):
    """Draw SVG path data onto canvas (assumes SVG coordinate space)."""
    segments = parse_path(d_string)
    p = canvas.beginPath()
    current = None

    for seg in segments:
        start = seg.start
        if current is None or abs(start - current) > 0.01:
            p.moveTo(start.real, start.imag)

        if isinstance(seg, Line):
            p.lineTo(seg.end.real, seg.end.imag)
        elif isinstance(seg, CubicBezier):
            p.curveTo(
                seg.control1.real,
                seg.control1.imag,
                seg.control2.real,
                seg.control2.imag,
                seg.end.real,
                seg.end.imag,
            )
        elif isinstance(seg, QuadraticBezier):
            s, ctrl, e = seg.start, seg.control, seg.end
            c1 = s + (2 / 3) * (ctrl - s)
            c2 = e + (2 / 3) * (ctrl - e)
            p.curveTo(c1.real, c1.imag, c2.real, c2.imag, e.real, e.imag)
        elif isinstance(seg, Arc):
            # Convert arc to cubic bezier curves
            for bez in arc_to_beziers(seg):
                p.curveTo(
                    bez[1].real,
                    bez[1].imag,
                    bez[2].real,
                    bez[2].imag,
                    bez[3].real,
                    bez[3].imag,
                )

        current = seg.end

    if d_string.rstrip()[-1:].lower() == "z":
        p.close()

    canvas.drawPath(p, stroke=1, fill=0)


def _inkscape(*args):
    """Run an Inkscape CLI command, returning completed process."""
    return subprocess.run(
        ["inkscape", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _svg_dimensions(svg_path):
    """Parse SVG dimensions, returning (vb_x, vb_y, svg_w, svg_h)."""
    tree = ET.parse(svg_path)
    root = tree.getroot()
    viewbox = root.get("viewBox")
    if viewbox:
        parts = viewbox.split()
        return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    return (
        0,
        0,
        float(re.sub(r"[^\d.]", "", root.get("width", "0"))),
        float(re.sub(r"[^\d.]", "", root.get("height", "0"))),
    )


def process_svg(input_path, output_path, append=False):
    """Convert a single SVG to a CutContour PDF."""
    if append:
        return _process_svg_append(input_path, output_path)

    # Parse SVG
    tree = ET.parse(input_path)
    root = tree.getroot()
    parent_map = {child: parent for parent in root.iter() for child in parent}

    # Get dimensions from viewBox or width/height
    vb_x, vb_y, svg_w, svg_h = _svg_dimensions(input_path)

    # PDF page size in points
    page_w = svg_w * SVG_PX_TO_PT
    page_h = svg_h * SVG_PX_TO_PT

    # Find all path elements
    paths = root.findall(f".//{SVG_NS}path") or root.findall(".//path")
    if not paths:
        print(f"Warning: No paths found in {input_path}", file=sys.stderr)

    # Create PDF with CutContour spot color
    c = Canvas(str(output_path), pagesize=(page_w, page_h))
    cutcontour_color = CMYKColorSep(0, 1, 0, 0, spotName="CutContour", density=1)
    c.setStrokeColor(cutcontour_color)
    c.setLineWidth(0.25)

    # Transform canvas from PDF coords to SVG coords (flip Y, scale, offset viewBox)
    c.translate(0, page_h)
    c.scale(SVG_PX_TO_PT, -SVG_PX_TO_PT)
    if vb_x or vb_y:
        c.translate(-vb_x, -vb_y)

    # Draw embedded images (the sticker artwork)
    images = root.findall(f".//{SVG_NS}image") or root.findall(".//image")
    for img_el in images:
        href = img_el.get(f"{XLINK_NS}href") or img_el.get("href")
        if not href:
            continue

        x = float(img_el.get("x", "0"))
        y = float(img_el.get("y", "0"))
        w = float(img_el.get("width", "0"))
        h = float(img_el.get("height", "0"))

        if href.startswith("data:"):
            _, data = href.split(",", 1)
            img_data = ImageReader(BytesIO(base64.b64decode(data)))
        else:
            img_data = str(input_path.parent / href)

        transform = get_ancestor_transform(img_el, parent_map)
        c.saveState()
        if transform != IDENTITY:
            c.transform(*transform)
        # Un-flip Y locally so the image renders right-side up
        c.translate(x, y + h)
        c.scale(1, -1)
        c.drawImage(img_data, 0, 0, width=w, height=h, mask="auto")
        c.restoreState()

    # Draw each path with its accumulated transform (CutContour)
    for path_el in paths:
        d = path_el.get("d")
        if not d:
            continue
        transform = get_ancestor_transform(path_el, parent_map)
        c.saveState()
        if transform != IDENTITY:
            c.transform(*transform)
        draw_path_on_canvas(c, d)
        c.restoreState()

    c.save()
    typer.echo(output_path)


def _process_svg_append(input_path, output_path):
    """Append mode: rasterize artwork + Bézier CutContour from Inkscape union."""
    vb_x, vb_y, svg_w, svg_h = _svg_dimensions(input_path)
    page_w = svg_w * SVG_PX_TO_PT
    page_h = svg_h * SVG_PX_TO_PT

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        png_path = tmp / "artwork.png"
        union_svg_path = tmp / "union.svg"

        # Export artwork as high-res PNG
        dpi = 300
        _inkscape(
            str(input_path),
            f"--export-filename={png_path}",
            "--export-type=png",
            f"--export-dpi={dpi}",
        )

        # Union all paths into a single outline SVG
        _inkscape(
            str(input_path),
            "--batch-process",
            f"--actions=select-all;path-union;export-filename:{union_svg_path};export-type:svg;export-do",
        )

        # Parse the unioned SVG for CutContour paths
        union_tree = ET.parse(union_svg_path)
        union_root = union_tree.getroot()
        union_parent_map = {
            child: parent for parent in union_root.iter() for child in parent
        }
        union_paths = union_root.findall(f".//{SVG_NS}path") or union_root.findall(
            ".//path"
        )
        union_vb_x, union_vb_y, union_svg_w, union_svg_h = _svg_dimensions(
            union_svg_path
        )

        # Build the PDF
        c = Canvas(str(output_path), pagesize=(page_w, page_h))

        # Transform canvas from PDF coords to SVG coords
        c.translate(0, page_h)
        c.scale(SVG_PX_TO_PT, -SVG_PX_TO_PT)
        if vb_x or vb_y:
            c.translate(-vb_x, -vb_y)

        # Draw rasterized artwork
        c.saveState()
        c.translate(vb_x, vb_y + svg_h)
        c.scale(1, -1)
        c.drawImage(str(png_path), 0, 0, width=svg_w, height=svg_h, mask="auto")
        c.restoreState()

        # Draw CutContour from unioned paths
        cutcontour_color = CMYKColorSep(0, 1, 0, 0, spotName="CutContour", density=1)
        c.setStrokeColor(cutcontour_color)
        c.setLineWidth(0.25)

        # The unioned SVG may have different viewBox dimensions, so adjust
        c.saveState()
        if union_vb_x or union_vb_y:
            c.translate(-union_vb_x + vb_x, -union_vb_y + vb_y)

        for path_el in union_paths:
            d = path_el.get("d")
            if not d:
                continue
            transform = get_ancestor_transform(path_el, union_parent_map)
            c.saveState()
            if transform != IDENTITY:
                c.transform(*transform)
            draw_path_on_canvas(c, d)
            c.restoreState()

        c.restoreState()
        c.save()
        typer.echo(output_path)


app = typer.Typer()


@app.command()
def main(
    svgs: Annotated[list[Path], typer.Argument(help="SVG file(s) to process")],
    append: Annotated[
        bool,
        typer.Option(
            "--append",
            help="Rasterize artwork and add a unified CutContour outline (requires Inkscape)",
        ),
    ] = False,
):
    """Generate CutContour PDF(s) from SVG file(s) for Roland VersaWorks."""
    if append and not shutil.which("inkscape"):
        typer.echo("Error: --append requires Inkscape to be installed", err=True)
        raise typer.Exit(1)
    for input_path in svgs:
        if not input_path.exists():
            typer.echo(f"Error: {input_path} not found", err=True)
            raise typer.Exit(1)
        if input_path.suffix.lower() != ".svg":
            typer.echo(f"Skipping non-SVG file: {input_path}", err=True)
            continue
        output_path = input_path.parent / f"{input_path.stem}-cutcontour.pdf"
        process_svg(input_path, output_path, append=append)


if __name__ == "__main__":
    app()
