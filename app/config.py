"""Application configuration, loaded from environment / .env file."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ParcelDesk"
    company_name: str = "My Company"
    public_base_url: str = "http://localhost:8000"

    # Security
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = "admin123"

    # Storage
    database_url: str = "sqlite:///./data/parceltrack.db"

    # Sync behaviour
    demo_mode: bool = False           # simulate carrier responses (no credentials needed)
    sync_on_startup: bool = True
    sync_interval_minutes: int = 30
    http_timeout_seconds: int = 20
    stuck_customs_days: int = 5       # alert if in customs this long
    stuck_transit_days: int = 14      # alert if in transit this long with no movement
    warehouse_stale_days: int = 7     # flag parcels sitting on the shelf this long

    # Poll parcels that are out for delivery more often than everything else
    ofd_sync_enabled: bool = True
    ofd_sync_minutes: int = 60

    # Printed labels (mm)
    label_width_mm: float = 100.0
    label_height_mm: float = 60.0
    label_module_mm: float = 0.33     # barcode X dimension

    # WhatsApp / SMS alerts
    messaging_enabled: bool = True
    messaging_provider: str = "none"          # whatsapp | twilio | webhook | none
    messaging_alert_statuses: str = ""        # empty -> same statuses as email alerts
    messaging_recipients: str = ""            # fallback numbers, comma separated (E.164)
    whatsapp_token: str = ""                  # Meta WhatsApp Cloud API permanent token
    whatsapp_phone_id: str = ""               # Your WhatsApp business phone number ID
    whatsapp_api_version: str = "v21.0"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""                     # e.g. +12025550123
    twilio_use_whatsapp: bool = False         # send through WhatsApp instead of SMS
    webhook_url: str = ""                     # generic HTTP gateway (aggregators, internal bots)
    webhook_token: str = ""
    webhook_payload_template: str = ""        # optional JSON template using {to} and {message}

    # Email alerts
    alerts_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "parcels@example.com"
    smtp_use_tls: bool = True         # STARTTLS (port 587)
    smtp_use_ssl: bool = False        # SMTPS (port 465)
    alert_on_statuses: str = "delivered,exception,customs,out_for_delivery"
    daily_digest_hour: int = 7        # local server time

    # Carrier: DHL Express (developer.dhl.com -> Shipment Tracking - Unified)
    dhl_api_key: str = ""
    dhl_api_secret: str = ""
    dhl_base_url: str = "https://express.api.dhl.com/mydhlapi"
    dhl_use_test: bool = False        # True -> .../mydhlapi/test

    # Carrier: FedEx (developer.fedex.com -> Track API)
    fedex_client_id: str = ""
    fedex_client_secret: str = ""
    fedex_account_number: str = ""
    fedex_base_url: str = "https://apis.fedex.com"
    fedex_use_sandbox: bool = False   # True -> https://apis-sandbox.fedex.com

    # Carrier: UPS (developer.ups.com -> Track API)
    ups_client_id: str = ""
    ups_client_secret: str = ""
    ups_account_number: str = ""
    ups_base_url: str = "https://onlinetools.ups.com"
    ups_use_test: bool = False        # True -> wwwcie.ups.com (test environment)

    # Carrier: DHL eCommerce / Parcel (DHL Unified Shipment Tracking API)
    # Same developer.dhl.com account, product "Shipment Tracking - Unified" (no /mydhlapi prefix)
    dhl_ecom_api_key: str = ""
    dhl_ecom_base_url: str = "https://api-eu.dhl.com"

    # Carrier: Colissimo / La Poste (Enterprise REST API)
    colissimo_api_key: str = ""        # X-Okapi-Key
    colissimo_contract_number: str = ""
    colissimo_password: str = ""
    colissimo_base_url: str = "https://ws.colissimo.fr"

    # Carrier: 17TRACK aggregator — covers EMS, China Post, postal operators and 3,000+ couriers
    track17_api_key: str = ""          # sent as the "17token" header
    track17_base_url: str = "https://api.17track.net/track/v2.2"

    # Carrier: Aramex (ws.aramex.net / account credentials)
    aramex_username: str = ""
    aramex_password: str = ""
    aramex_account_number: str = ""
    aramex_account_pin: str = ""
    aramex_account_entity: str = ""
    aramex_account_country_code: str = "MG"
    aramex_base_url: str = "https://ws.aramex.net/ShippingAPI.V2"

    @property
    def dhl_url(self) -> str:
        return f"{self.dhl_base_url}/test" if self.dhl_use_test else self.dhl_base_url

    @property
    def ups_url(self) -> str:
        return "https://wwwcie.ups.com" if self.ups_use_test else self.ups_base_url

    @property
    def fedex_url(self) -> str:
        return "https://apis-sandbox.fedex.com" if self.fedex_use_sandbox else self.fedex_base_url

    @property
    def alert_status_set(self) -> set[str]:
        return {s.strip().lower() for s in self.alert_on_statuses.split(",") if s.strip()}

    @property
    def messaging_status_set(self) -> set[str]:
        source = self.messaging_alert_statuses or self.alert_on_statuses
        return {s.strip().lower() for s in source.split(",") if s.strip()}

    @property
    def messaging_number_list(self) -> list[str]:
        return [n.strip() for n in self.messaging_recipients.split(",") if n.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
