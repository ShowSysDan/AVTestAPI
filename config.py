"""Application configuration and default settings.

Settings the user can change at runtime (API key, base URL, etc.) live in the
SQLite ``settings`` table; the values here are only the seed defaults used the
first time the database is created.
"""

import os

# Where the SQLite database lives.
DB_PATH = os.environ.get("AVTEST_DB", os.path.join(os.path.dirname(__file__), "avtest.db"))

# Flask secret (only used for flash messages / sessions in this test app).
SECRET_KEY = os.environ.get("AVTEST_SECRET_KEY", "dev-secret-change-me")

# --- Default ArtsVision settings (seeded into the DB on first run) -----------
# LabVision stores the full ".../api/getdata" URL and strips the endpoint. We
# store the API *base* instead and append the endpoint per request.
DEFAULT_SETTINGS = {
    "api_base_url": "https://av2.artsvision.net/api",
    "api_key": "",
    "ssl_verify": "1",            # "1" / "0"
    "read_endpoint": "getdata",
    # Per the ArtsVision API docs, writes go to SaveData, which accepts a single
    # ApiDataEntity ({Entity, Rows:[...]}). RowState values are:
    #   None = 0, Modified = 1, Added = 2, Deleted = 3
    # so an edited event row is flagged Modified = 1. Endpoint name and the
    # modified RowState remain configurable for flexibility.
    "write_endpoint": "savedata",
    "write_row_state": "1",        # RowState value that marks a row "modified"
    "default_entity": "Event",
    # Default event-list filter.
    "default_event_status": "Confirmed",
}

# HTTP timeout (seconds) for all API calls.
REQUEST_TIMEOUT = 30

# Curated, low-risk fields surfaced as primary editable inputs on the edit
# form. Every other populated field is still editable under "all fields".
CURATED_FIELDS = [
    "Text for Calendar",
    "Marquee Text",
    "Event Notes",
    "General Info Other Notes",
    "Notes",
    "Notes to Manager",
    "Event Status",
    "Expected Attendance",
    "Contact Name",
    "Contact Phone",
]
