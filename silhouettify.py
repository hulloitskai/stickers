#!/usr/bin/env python3
"""silhouettify.py - Convert PNG files to black silhouettes."""

from pathlib import Path
from typing import Annotated, Optional
import typer
from PIL import Image


def make_silhouette(input_path: Path, output_path: Path) -> None:
    img = Image.open(input_path).convert("RGBA")
    _, _, _, alpha = img.split()
    alpha_thresh = alpha.point(lambda x: 255 if x > 0 else 0)
    silhouette = Image.new("RGBA", img.size, (0, 0, 0, 255))
    silhouette.putalpha(alpha_thresh)
    silhouette.save(output_path)


app = typer.Typer()


@app.command()
def main(
    inputs: Annotated[list[Path], typer.Argument(help="PNG file(s) to process")],
    output_dir: Annotated[Optional[Path], typer.Option(help="Output directory (default: same as input)")] = None,
):
    """Convert PNG files to black silhouettes."""
    if output_dir and not output_dir.is_dir():
        typer.echo(f"Error: output directory not found: {output_dir}", err=True)
        raise typer.Exit(1)

    errors = False
    for input_path in inputs:
        if not input_path.exists():
            typer.echo(f"Error: file not found: {input_path}", err=True)
            errors = True
            continue
        if input_path.suffix.lower() != ".png":
            typer.echo(f"Error: not a PNG file: {input_path}", err=True)
            errors = True
            continue

        out_dir = output_dir if output_dir else input_path.parent
        output_path = out_dir / f"{input_path.stem}-silhouette.png"
        make_silhouette(input_path, output_path)
        typer.echo(output_path)

    if errors:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
