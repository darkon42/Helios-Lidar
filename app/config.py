"""Runtime configuration loaded from environment variables.

Pydantic Settings reads values from the process environment (or a `.env`
file in development) and exposes them as a typed `Settings` instance the
rest of the app imports. Production overrides go through the systemd
unit's Environment= directives.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HELIOS_LIDAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    #Public URL the app is served behind. Used to build absolute links
    #to the produced COG and in the ready-to-paste YAML snippet.
    public_base_url: str = "http://127.0.0.1:8000"

    #Where uploaded inputs land before being processed. Cleaned daily
    #by the cron under deploy/.
    jobs_dir: Path = Path("/var/helios-lidar/jobs")

    #Where finished COGs live, served back over HTTPS with CORS on.
    output_dir: Path = Path("/var/helios-lidar/output")

    #Upper bound on a single upload, in bytes. Default 4 GB so a chunky
    #LAZ tile from a typical national LiDAR programme fits.
    max_upload_bytes: int = 4 * 1024 * 1024 * 1024

    #Pixel pitch (metres) for the rasterised DSM when the input is a
    #point cloud. 1 m is the standard Helios consumes; bumping this
    #down to 0.5 m doubles the file size and PDAL processing time for
    #limited shadow-quality gain in the card.
    raster_pixel_meters: float = 1.0


settings = Settings()
