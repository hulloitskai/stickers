# stickers

Create and cut your own custom stickers using a Roland VersaWorks vinyl cutter.

## Usage

See: https://www.loom.com/share/d3a934b9ef2d46a0a5c6d581f5440f7f

## Tools

### silhouettify.py

Creates silhouette masks from PNG images using ImageMagick.

```bash
mise silhouettify ./<dir>/<file>.png  # creates ./<dir>/<file>-silhouette.png
```

### cutcontour.py

Prepares SVG files for Roland VersaWorks cutters by:

- Setting stroke color to `#ff00ff` (100% magenta spot color)
- Setting stroke width to `0.25` (thin stroke for cutting)
- Setting fill to `none`
- Adding `id="CutContour"` for VersaWorks recognition

```bash
mise cutcontour ./<dir>/<file>.svg    # creates ./<dir>/<file>-cutcontour.pdf
```

### resize.py

Resizes PDF(s) to a target height or width in centimeters, preserving aspect ratio. Output: `<basename>-sized.pdf` in the same directory as the input.

```bash
mise resize -H 10 ./<dir>/<file>.pdf  # creates ./<dir>/<file>-sized.pdf (10cm height)
mise resize -W 10 ./<dir>/<file>.pdf  # creates ./<dir>/<file>-sized.pdf (10cm width)
```
