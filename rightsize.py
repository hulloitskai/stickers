#!/usr/bin/env python3

"""
rightsize.py - Shrink-wrap SVG viewport to content

Resizes an SVG's artboard/viewport to tightly fit its content with 1px visual padding,
accounting for stroke width on paths.
"""

import re
from pathlib import Path
import sys
from typing import Annotated
import xml.etree.ElementTree as ET
import typer
from svgpathtools import parse_path

SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK_NS = "{http://www.w3.org/1999/xlink}"
IDENTITY = (1, 0, 0, 1, 0, 0)


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
            import math

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


def parse_stroke_width(style_str):
    """Extract stroke-width from CSS style attribute string.

    Args:
        style_str: The style attribute value (e.g., "stroke:#000;stroke-width:2px")

    Returns:
        stroke-width as float, defaulting to 1.0 if not found
    """
    if not style_str:
        return 1.0
    for item in style_str.split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "stroke-width":
                # Remove units like 'px' if present
                v = re.sub(r"[^\d.]", "", v)
                try:
                    return float(v)
                except ValueError:
                    return 1.0
    return 1.0


def transform_bbox(bbox, matrix):
    """Apply affine transform to a bounding box.

    Args:
        bbox: Tuple (xmin, ymin, xmax, ymax) in local coords
        matrix: Affine transform tuple (a, b, c, d, e, f)

    Returns:
        Transformed bounding box (xmin, ymin, xmax, ymax) in SVG-space coords
    """
    xmin, ymin, xmax, ymax = bbox
    # Transform all four corners
    corners = [
        (xmin, ymin),
        (xmax, ymin),
        (xmin, ymax),
        (xmax, ymax),
    ]
    transformed = []
    for x, y in corners:
        tx = matrix[0] * x + matrix[2] * y + matrix[4]
        ty = matrix[1] * x + matrix[3] * y + matrix[5]
        transformed.append((tx, ty))
    # Compute new bounding box
    xs = [p[0] for p in transformed]
    ys = [p[1] for p in transformed]
    return (min(xs), min(ys), max(xs), max(ys))


def union_bbox(bbox1, bbox2):
    """Union two bounding boxes."""
    if bbox1 is None:
        return bbox2
    if bbox2 is None:
        return bbox1
    x1 = min(bbox1[0], bbox2[0])
    y1 = min(bbox1[1], bbox2[1])
    x2 = max(bbox1[2], bbox2[2])
    y2 = max(bbox1[3], bbox2[3])
    return (x1, y1, x2, y2)


def compute_content_bounds(root):
    """Walk all <path> and <image> elements and compute union of their transformed bounding boxes.

    Args:
        root: SVG root element

    Returns:
        Combined bounding box (xmin, ymin, xmax, ymax) or None if no content found
    """
    parent_map = {child: parent for parent in root.iter() for child in parent}
    combined_bbox = None

    # Process all path elements
    paths = root.findall(f".//{SVG_NS}path") or root.findall(".//path")
    for path_el in paths:
        d = path_el.get("d")
        if not d:
            continue

        # Get path bounding box in local coords
        # Note: svgpathtools.bbox() returns (xmin, xmax, ymin, ymax)
        try:
            p = parse_path(d)
            raw_bbox = p.bbox()
            # Convert to (xmin, ymin, xmax, ymax)
            local_bbox = (raw_bbox[0], raw_bbox[2], raw_bbox[1], raw_bbox[3])
        except Exception:
            continue

        # Get ancestor transform and apply to bbox
        transform = get_ancestor_transform(path_el, parent_map)
        svg_bbox = transform_bbox(local_bbox, transform)
        combined_bbox = union_bbox(combined_bbox, svg_bbox)

    # Process all image elements
    images = root.findall(f".//{SVG_NS}image") or root.findall(".//image")
    for img_el in images:
        x = float(img_el.get("x", "0"))
        y = float(img_el.get("y", "0"))
        w = float(img_el.get("width", "0"))
        h = float(img_el.get("height", "0"))

        if w <= 0 or h <= 0:
            continue

        local_bbox = (x, y, x + w, y + h)
        transform = get_ancestor_transform(img_el, parent_map)
        svg_bbox = transform_bbox(local_bbox, transform)
        combined_bbox = union_bbox(combined_bbox, svg_bbox)

    return combined_bbox


def get_max_stroke_width(root):
    """Find the maximum stroke-width among all path elements.

    Args:
        root: SVG root element

    Returns:
        Maximum stroke-width found, or 1.0 as default
    """
    max_stroke = 1.0
    paths = root.findall(f".//{SVG_NS}path") or root.findall(".//path")
    for path_el in paths:
        # Check style attribute
        style = path_el.get("style", "")
        stroke = parse_stroke_width(style)
        if stroke > max_stroke:
            max_stroke = stroke
        # Also check direct stroke-width attribute
        sw = path_el.get("stroke-width")
        if sw:
            try:
                val = float(re.sub(r"[^\d.]", "", sw))
                if val > max_stroke:
                    max_stroke = val
            except ValueError:
                pass
    return max_stroke


def rightsize_svg(input_path, output_path, padding=1.0):
    """Resize SVG viewport to tightly fit content.

    Args:
        input_path: Path to input SVG file
        output_path: Path to output SVG file
        padding: Visual padding in pixels to add on all sides (default 1.0)

    Returns:
        True if successful, False if skipped (e.g., no content found)
    """
    # Parse SVG
    tree = ET.parse(input_path)
    root = tree.getroot()

    # Compute content bounds
    content_bbox = compute_content_bounds(root)

    if content_bbox is None:
        print(f"Warning: No paths or images found in {input_path}", file=sys.stderr)
        return False

    # Expand by stroke-width / 2 on all sides
    max_stroke = get_max_stroke_width(root)
    stroke_expansion = max_stroke / 2

    # Add padding
    total_expansion = stroke_expansion + padding

    xmin = content_bbox[0] - total_expansion
    ymin = content_bbox[1] - total_expansion
    xmax = content_bbox[2] + total_expansion
    ymax = content_bbox[3] + total_expansion

    new_width = xmax - xmin
    new_height = ymax - ymin

    # Update SVG root attributes
    root.set("viewBox", f"{xmin} {ymin} {new_width} {new_height}")
    root.set("width", f"{new_width}")
    root.set("height", f"{new_height}")

    # Write output
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    # Add newline at end
    with open(output_path, "a") as f:
        f.write("\n")

    return True


app = typer.Typer()


@app.command()
def main(
    svgs: Annotated[list[Path], typer.Argument(help="SVG file(s) to process")],
    padding: Annotated[
        float,
        typer.Option("--padding", "-p", help="Visual padding in pixels (default: 1.0)"),
    ] = 1.0,
):
    """Resize SVG viewport to tightly fit content with padding."""
    for input_path in svgs:
        if not input_path.exists():
            typer.echo(f"Error: {input_path} not found", file=sys.stderr)
            raise typer.Exit(1)
        if input_path.suffix.lower() != ".svg":
            typer.echo(f"Skipping non-SVG file: {input_path}", file=sys.stderr)
            continue

        output_path = input_path.parent / f"{input_path.stem}-rightsized.svg"

        if rightsize_svg(input_path, output_path, padding=padding):
            typer.echo(output_path)


if __name__ == "__main__":
    app()
