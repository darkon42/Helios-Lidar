"""Rasterise a LAS / LAZ point cloud directly into a height-above-
ground (nDSM) Float32 GeoTIFF.

This skips the intermediate DSM + DTM raster pair the two-input flow
needs: we compute the per-point height relative to the nearest ground
point first, then take the per-cell maximum of those heights. Matches
the result of PDAL's `filters.hag_nn` + `writers.gdal` with
`output_type=max`, but in pure-Python on top of laspy (with the
`lazrs` Rust LAZ codec) + scipy (cKDTree) + the GDAL Python bindings
the rest of the pipeline already speaks. No system PDAL needed,
which sidesteps the absence of PDAL packages in Ubuntu 25.04 plucky
and the UbuntuGIS PPA's missing plucky release.

The implementation expects classified LiDAR (the standard 1 byte
per point with code 2 = ground, the ASPRS spec used by virtually
every modern national LiDAR programme). If a file has no ground-
classified points we fail with a user-facing message rather than
guessing a ground filter; that decision belongs upstream.

Memory: a 1 km x 1 km tile at 10 points / m^2 holds ~ 10 M points,
~ 240 MB resident as four Float64 arrays (x, y, z, hag). The VPS
has ~ 6 GB free RAM so a 50 M-point tile (~ 1.2 GB) still fits.
Larger inputs would need chunked processing; we'll add that when a
real input hits the limit.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import laspy
import numpy as np
from osgeo import gdal, osr
from scipy.spatial import cKDTree

from pipeline.dsm_to_ndsm import NDSM_NODATA
from pipeline.validate import ValidationError

#ASPRS Standard LIDAR Point Classes, ground returns are class 2.
GROUND_CLASS: int = 2

#K nearest ground neighbours averaged for the per-point ground
#elevation lookup. 1 is closest to PDAL's filters.hag_nn but tends to
#pick up noisy outliers right at the bottom of building walls; 3 is a
#robust middle ground.
GROUND_KNN: int = 3


#10 query chunks so the on_progress callback can tick the bar
#through the KDTree pass instead of jumping from 25 % to 75 % when
#one giant scipy call returns.
QUERY_CHUNKS: int = 10


def rasterise(
    laz_path: Path,
    output_path: Path,
    pixel_meters: float = 1.0,
    on_progress: Callable[[str, float], None] | None = None,
) -> None:
    """Write the nDSM raster derived from `laz_path` at the given
    cell pitch (default 1 m, matching the rest of the Helios
    pipeline).

    `on_progress(phase, fraction)` is called with `fraction` in [0, 1]
    at each phase boundary so a long-running caller (a FastAPI
    BackgroundTask in our case) can surface a moving progress bar
    instead of the bare 0 % -> 100 % step the unchunked version
    showed. The phase strings are stable: "reading", "kdtree",
    "querying", "rasterising", "writing".

    Raises:
        ValidationError: when the input has no usable ground returns
            or no resolvable CRS; the message is shown verbatim in
            the job status JSON.
    """
    gdal.UseExceptions()
    report = on_progress or (lambda _phase, _frac: None)

    report("reading", 0.0)
    with laspy.open(str(laz_path)) as reader:
        header = reader.header
        crs = header.parse_crs()
        if crs is None:
            raise ValidationError(
                "The LAS / LAZ file has no embedded coordinate "
                "reference system. Reproject and embed a CRS before "
                "uploading."
            )
        points = reader.read()
    report("reading", 1.0)

    x = np.asarray(points.x, dtype=np.float64)
    y = np.asarray(points.y, dtype=np.float64)
    z = np.asarray(points.z, dtype=np.float64)
    classification = np.asarray(points.classification, dtype=np.uint8)

    if x.size == 0:
        raise ValidationError("The LAS / LAZ file contains no points.")

    ground_mask = classification == GROUND_CLASS
    ground_count = int(ground_mask.sum())
    if ground_count < 10:
        raise ValidationError(
            f"The LAS / LAZ file has only {ground_count} ground-classified "
            "points (ASPRS class 2). A height-above-ground raster needs a "
            "classified ground surface; re-run the LiDAR processing chain "
            "with a ground filter (PMF, SMRF) before uploading."
        )

    #Compute height-above-ground for every point: query the K nearest
    #ground points in (x, y), take the mean of their Z, subtract from
    #the point's Z. cKDTree on 2D is the right shape because we're
    #asking "what's the ground elevation directly below this point",
    #not a true 3D nearest neighbour.
    report("kdtree", 0.0)
    ground_xy = np.column_stack((x[ground_mask], y[ground_mask]))
    ground_z = z[ground_mask]
    tree = cKDTree(ground_xy)
    report("kdtree", 1.0)

    #Chunked KDTree query so we can tick the progress bar between
    #batches. Single-shot tree.query on 26 M points blocks for ~30 s
    #with the progress bar visually frozen; ten 2.6 M-point batches
    #take essentially the same wall-clock total but report nine
    #intermediate progress updates the caller can surface.
    k = min(GROUND_KNN, ground_count)
    n_points = x.size
    chunk_size = max(1, n_points // QUERY_CHUNKS)
    nn_idx = np.empty((n_points, k) if k > 1 else n_points, dtype=np.intp)
    for start in range(0, n_points, chunk_size):
        end = min(start + chunk_size, n_points)
        chunk_xy = np.column_stack((x[start:end], y[start:end]))
        _, chunk_idx = tree.query(chunk_xy, k=k, workers=-1)
        nn_idx[start:end] = chunk_idx
        report("querying", end / n_points)

    if k == 1:
        ground_z_per_point = ground_z[nn_idx]
    else:
        ground_z_per_point = ground_z[nn_idx].mean(axis=1)
    hag = (z - ground_z_per_point).astype(np.float32)
    np.maximum(hag, 0.0, out=hag)

    #Bin to a raster: bbox snapped to integer pixel multiples so the
    #output stays clean at any pixel pitch. Y axis flipped because
    #raster rows scan top-to-bottom.
    min_x_snap = np.floor(x.min() / pixel_meters) * pixel_meters
    max_x_snap = np.ceil(x.max() / pixel_meters) * pixel_meters
    min_y_snap = np.floor(y.min() / pixel_meters) * pixel_meters
    max_y_snap = np.ceil(y.max() / pixel_meters) * pixel_meters
    width = int(round((max_x_snap - min_x_snap) / pixel_meters))
    height = int(round((max_y_snap - min_y_snap) / pixel_meters))
    if width == 0 or height == 0:
        raise ValidationError(
            "The LAS / LAZ file footprint collapses to less than one "
            "raster cell at the configured 1 m pitch. The file is "
            "probably empty or has corrupt coordinates."
        )

    col = np.clip(((x - min_x_snap) / pixel_meters).astype(np.int64), 0, width - 1)
    row = np.clip(((max_y_snap - y) / pixel_meters).astype(np.int64), 0, height - 1)

    #Per-cell max-Z aggregation. np.maximum.at is the accumulator-
    #style ufunc for "take the per-cell max over a sequence of
    #unordered writes"; ~ O(points) and avoids a Python loop.
    report("rasterising", 0.0)
    raster = np.full((height, width), NDSM_NODATA, dtype=np.float32)
    np.maximum.at(raster, (row, col), hag)
    #Any cell that never saw a point stays at NDSM_NODATA.
    report("rasterising", 1.0)

    #Write as a Float32 GeoTIFF with the right projection so the
    #downstream cog step + the Helios bbox lookup work unchanged.
    report("writing", 0.0)
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(
        str(output_path),
        xsize=width,
        ysize=height,
        bands=1,
        eType=gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    #(origin_x, pixel_w, 0, origin_y, 0, -pixel_h) , Y step negative
    #because rows scan top to bottom.
    out_ds.SetGeoTransform((min_x_snap, pixel_meters, 0.0, max_y_snap, 0.0, -pixel_meters))

    srs = osr.SpatialReference()
    srs.ImportFromWkt(crs.to_wkt())
    out_ds.SetProjection(srs.ExportToWkt())

    band = out_ds.GetRasterBand(1)
    band.SetNoDataValue(NDSM_NODATA)
    band.WriteArray(raster)
    band.FlushCache()
    out_ds.FlushCache()
    out_ds = None
    report("writing", 1.0)
