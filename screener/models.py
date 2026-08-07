from dataclasses import dataclass, field


@dataclass
class Listing:
    source: str          # "propertyguru" | "99co"
    source_id: str
    url: str
    project_name: str
    address: str
    postal_code: str | None
    district: str        # "D09" format
    price: int           # SGD
    bedrooms: int | None
    bathrooms: int | None
    size_sqft: float | None
    tenure: str | None
    image_url: str | None
    description: str | None
    listed_at: str | None

    # Enriched fields
    shelter_status: str = "unverified"   # "confirmed" | "unverified" | "absent"
    nearby_schools: list[str] = field(default_factory=list)
    nearby_mrt: list[str] = field(default_factory=list)
    geocode_ok: bool = False
    lat: float | None = None
    lng: float | None = None

    def completeness(self) -> int:
        """Count of non-None non-empty fields — used for dedup tie-breaking."""
        fields = [
            self.postal_code, self.bedrooms, self.bathrooms,
            self.size_sqft, self.tenure, self.image_url,
            self.description, self.listed_at,
        ]
        return sum(1 for f in fields if f is not None)
