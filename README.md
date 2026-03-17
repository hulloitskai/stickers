# stickers

my personal collection of printable stickers.

```bash
./silhouettify.sh ./<dir>/<file>.png  # creates ./<dir>/<file>-silhouette.png
./cutcontour.py ./<dir>/<file>.svg    # creates ./<dir>/<file>-cutcontour.svg
```

## Tools

### silhouettify.sh
Creates silhouette masks from PNG images using ImageMagick.

### cutcontour.py
Prepares SVG files for Roland VersaWorks cutters by:
- Setting stroke color to `#ff00ff` (100% magenta spot color)
- Setting stroke width to `0.25` (thin stroke for cutting)
- Setting fill to `none`
- Adding `id="CutContour"` for VersaWorks recognition
