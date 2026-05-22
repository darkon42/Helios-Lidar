"""Conversion pipeline: LAS / LAZ point cloud OR a DSM + DTM raster
pair into a height-above-ground (nDSM) Cloud-Optimized GeoTIFF.

The pipeline is split into single-responsibility modules so a fixture
test can target each step without booting the whole FastAPI app:

* `validate` , GDAL-side inspection + same-CRS / same-grid check
  between a DSM and a DTM, with corner reprojection to WGS84 for
  the bbox the Helios card needs.
* `dsm_to_ndsm` , per-pixel subtraction of the DTM from the DSM into
  a Float32 nDSM raster (raster_pair workflow).
* `laz_to_ndsm` , laspy + scipy.cKDTree implementation of the
  point-cloud workflow: per-point height above 3 nearest ground
  points, then per-cell max-Z aggregation into a Float32 raster.
* `cog` , wraps a Float32 GeoTIFF as a Cloud-Optimized GeoTIFF with
  internal tiling and overview pyramids, ready to be range-fetched
  by the Helios browser client.
* `yaml_snippet` , renders the `lidar-local-ndsm-*` YAML block the
  user pastes into their Helios card config.

Each module is a thin shell around the upstream library (GDAL,
laspy, scipy) so most of the lift is delegated and the tests can
focus on the seams.
"""
