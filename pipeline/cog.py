"""Wrap a Float32 GeoTIFF as a Cloud-Optimized GeoTIFF.

GDAL's COG driver builds a tiled GeoTIFF with overviews laid out in
exactly the order range-fetchers expect, so the Helios card can
issue an HTTP range request for the home's bbox and pull only the
~few KB of pixel data covering it instead of the whole file. Without
COG-ification a multi-megabyte nDSM gets downloaded in full on every
home-position change, which would make the shadow refresh visibly
slow on a typical home connection.

DEFLATE + PREDICTOR=2 is the right combo for Float32 elevation data:
horizontal differencing keeps the entropy low because neighbouring
ground samples are close in height, which DEFLATE then compresses
well.
"""

from __future__ import annotations

from pathlib import Path

from osgeo import gdal


def cogify(input_path: Path, output_path: Path) -> None:
    """Translate the input GeoTIFF into a Cloud-Optimized GeoTIFF at
    `output_path`, with internal tiling and overview pyramids.
    """
    gdal.UseExceptions()
    gdal.Translate(
        str(output_path),
        str(input_path),
        format="COG",
        creationOptions=[
            "COMPRESS=DEFLATE",
            "PREDICTOR=2",
            "BLOCKSIZE=512",
            "RESAMPLING=AVERAGE",
            "OVERVIEWS=AUTO",
            "BIGTIFF=IF_SAFER",
        ],
    )
