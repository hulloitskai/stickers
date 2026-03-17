#!/usr/bin/env python3
"""
resize.py - Resize PDF(s) to a target height or width in centimeters

Preserves aspect ratio. Output: <basename>-sized.pdf in same directory as input.
"""

from pathlib import Path
from typing import List, Optional

import subprocess
import sys

import typer
from pypdf import PdfReader, PdfWriter

CM_TO_PT = 72 / 2.54
app = typer.Typer()


def process_pdf(input_path: Path, output_path: Path, target_h_cm: float | None, target_w_cm: float | None) -> None:
    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    for page in reader.pages:
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)

        if target_h_cm is not None:
            scale = (target_h_cm * CM_TO_PT) / page_h
        else:
            scale = (target_w_cm * CM_TO_PT) / page_w

        page.scale_by(scale)
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


@app.command()
def main(
    inputs: List[Path] = typer.Argument(..., metavar="FILE.pdf"),
    height: Optional[float] = typer.Option(None, "-H", "--height", metavar="CM", help="Target height in cm"),
    width: Optional[float] = typer.Option(None, "-W", "--width", metavar="CM", help="Target width in cm"),
    open_after: bool = typer.Option(False, "--open", help="Open the output file after processing"),
):
    """Resize PDF(s) to a target height or width in centimeters, preserving aspect ratio."""
    if height is None and width is None:
        typer.echo("Error: one of -h/--height or -w/--width is required", err=True)
        raise typer.Exit(1)
    if height is not None and width is not None:
        typer.echo("Error: -h/--height and -w/--width are mutually exclusive", err=True)
        raise typer.Exit(1)

    cm = height if height is not None else width
    if cm <= 0:
        typer.echo(f"Error: cm value must be positive, got {cm}", err=True)
        raise typer.Exit(1)

    errors = False
    for input_path in inputs:
        if not input_path.exists():
            typer.echo(f"Error: file not found: {input_path}", err=True)
            errors = True
            continue
        if input_path.suffix.lower() != ".pdf":
            typer.echo(f"Error: not a PDF file: {input_path}", err=True)
            errors = True
            continue

        output_path = input_path.parent / f"{input_path.stem}-sized.pdf"
        try:
            process_pdf(input_path, output_path, height, width)
            typer.echo(output_path)
            if open_after:
                if sys.platform == "darwin":
                    subprocess.run(["open", str(output_path)])
                elif sys.platform == "win32":
                    subprocess.run(["start", str(output_path)], shell=True)
                else:
                    subprocess.run(["xdg-open", str(output_path)])
        except Exception as e:
            typer.echo(f"Error processing {input_path}: {e}", err=True)
            errors = True

    if errors:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
