"""Every job the scheduler knows, by name: what the API and its clients call them."""

from enum import StrEnum


class JobName(StrEnum):
    SCRAPE = "scrape"  # Source Collection; the jobs of ADR 06 §5 follow it
    FORECAST = "forecast"  # every municipality scored for the next heat network tender
