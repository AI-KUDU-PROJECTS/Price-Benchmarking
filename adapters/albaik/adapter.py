"""Official app pickup and delivery, composed with the existing HS overlay."""
from pathlib import Path
from adapters.sqlite_monitor import SQLiteMonitorAdapter
from bff.contract import BrandCapabilities
from competitors.albaik import app_config as config


class AlbaikAdapter(SQLiteMonitorAdapter):
    def __init__(self, db_path: Path | None = None):
        super().__init__(brand_id="albaik", brand_name="AlBaik",
                         db_path=db_path or config.DB_PATH,
                         branch_id=config.BRANCH_ID,
                         location_label="ALBAIK app · Arubah pickup / delivery nearby, Olaya, Riyadh")

    def _capabilities(self):
        return BrandCapabilities(has_discount=False, has_size_prices=False, has_images=True)

    def get_brand(self):
        brand = super().get_brand()
        brand.channels = ["pickup", "delivery"]
        return brand
