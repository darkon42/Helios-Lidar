"""Sanity-check uploaded DSM and DTM rasters before kicking off
processing. The pipeline reads heights with GDAL, so anything GDAL
can't open is a hard fail; beyond that we want the DSM and DTM to be
in the same coordinate system, the same grid, and the same footprint
so per-pixel subtraction makes sense.

The checks deliberately stop short of reprojecting or resampling one
raster to match the other. If a user uploads inputs that don't match,
we'd rather refuse and explain than silently produce a misaligned
nDSM that would render shadows in the wrong place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from osgeo import gdal, osr


@dataclass(frozen=True)
class RasterMetadata:
    """What we extract from a GeoTIFF for validation + downstream use."""

    path: Path
    width: int
    height: int
    crs_wkt: str
    epsg: int | None
    geotransform: tuple[float, float, float, float, float, float]
    pixel_size_x: float
    pixel_size_y: float
    bounds_native: tuple[float, float, float, float]
    """`(minX, minY, maxX, maxY)` in the raster's own CRS."""
    bounds_wgs84: tuple[float, float, float, float]
    """`(minLon, minLat, maxLon, maxLat)`. Always populated."""
    data_type: str
    nodata: float | None


class ValidationError(Exception):
    """User-facing validation failure. The message is shown verbatim
    in the job status JSON, so phrase it for a non-expert user.
    """


def inspect(path: Path) -> RasterMetadata:
    """Read metadata from a single GeoTIFF and reproject its corners
    into WGS84 so the caller can build the `lidar-local-ndsm-*`
    bbox in lat / lon regardless of the source projection.
    """
    gdal.UseExceptions()
    try:
        ds = gdal.Open(str(path))
    except RuntimeError as exc:
        raise ValidationError(f"GDAL cannot open {path.name}: {exc}") from exc
    if ds is None:
        raise ValidationError(f"GDAL returned no dataset for {path.name}")

    gt = ds.GetGeoTransform()
    if gt == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        raise ValidationError(
            f"{path.name} has no geotransform; the file is missing georeferencing."
        )

    proj_wkt = ds.GetProjection()
    if not proj_wkt:
        raise ValidationError(
            f"{path.name} has no coordinate reference system embedded."
        )

    band = ds.GetRasterBand(1)
    data_type = gdal.GetDataTypeName(band.DataType)
    nodata = band.GetNoDataValue()

    width, height = ds.RasterXSize, ds.RasterYSize
    pixel_size_x = abs(gt[1])
    pixel_size_y = abs(gt[5])

    #Native CRS corner bounds from the geotransform. Rows scan top
    #to bottom so the Y origin is at maxY and Y step is negative.
    min_x = gt[0]
    max_x = gt[0] + width * gt[1]
    max_y = gt[3]
    min_y = gt[3] + height * gt[5]
    bounds_native = (min_x, min_y, max_x, max_y)

    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(proj_wkt)
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    tgt_srs = osr.SpatialReference()
    tgt_srs.ImportFromEPSG(4326)
    tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(src_srs, tgt_srs)
    #Project the four corners and take the enclosing bbox; this is
    #robust to rotated grids that a naive (min_x, min_y) -> lon, lat
    #transform would distort.
    corners_native = [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y),
    ]
    lons: list[float] = []
    lats: list[float] = []
    for x, y in corners_native:
        lon, lat, _ = transform.TransformPoint(x, y)
        lons.append(lon)
        lats.append(lat)
    bounds_wgs84 = (min(lons), min(lats), max(lons), max(lats))

    epsg: int | None = None
    if src_srs.AutoIdentifyEPSG() == 0:
        epsg_str = src_srs.GetAuthorityCode(None)
        if epsg_str:
            epsg = int(epsg_str)

    return RasterMetadata(
        path=path,
        width=width,
        height=height,
        crs_wkt=proj_wkt,
        epsg=epsg,
        geotransform=gt,
        pixel_size_x=pixel_size_x,
        pixel_size_y=pixel_size_y,
        bounds_native=bounds_native,
        bounds_wgs84=bounds_wgs84,
        data_type=data_type,
        nodata=nodata,
    )


def validate_pair(dsm_path: Path, dtm_path: Path) -> tuple[RasterMetadata, RasterMetadata]:
    """Make sure the DSM and DTM line up on the same grid in the same
    CRS so a per-pixel subtraction is meaningful. Returns the two
    metadata objects on success; raises ValidationError on the first
    detected mismatch with a message that names the failing check.
    """
    dsm = inspect(dsm_path)
    dtm = inspect(dtm_path)

    if dsm.crs_wkt != dtm.crs_wkt:
        raise ValidationError(
            "DSM and DTM are in different coordinate reference systems. "
            "Reproject one to match the other before uploading."
        )

    if (dsm.width, dsm.height) != (dtm.width, dtm.height):
        raise ValidationError(
            f"DSM is {dsm.width}x{dsm.height} but DTM is {dtm.width}x{dtm.height}. "
            "The two rasters must share the same grid; resample one to the "
            "other's pitch before uploading."
        )

    #Geotransform mismatch tolerance: anything coarser than 1 % of the
    #pixel size is treated as a real misalignment. Floating-point
    #differences from a round-trip through QGIS or rasterio sit well
    #under that bar.
    tol_x = dsm.pixel_size_x * 0.01
    tol_y = dsm.pixel_size_y * 0.01
    for i, (a, b, tol) in enumerate(
        zip(
            dsm.geotransform,
            dtm.geotransform,
            (tol_x, tol_x, tol_x, tol_y, tol_y, tol_y),
            strict=True,
        )
    ):
        if abs(a - b) > tol:
            raise ValidationError(
                f"DSM and DTM geotransforms differ at component {i} "
                f"(DSM={a}, DTM={b}). Align the rasters on the same grid "
                "before uploading."
            )

    return dsm, dtm
