"""`build_datasette` settings that only matter in production.

Behind nginx the app sees plain-HTTP requests, so Datasette must be
told the public scheme or its absolute URLs (the dashboard charts'
data URL) are `http://` and get blocked as mixed content.
"""

import pytest
from datasette.utils.asgi import Request

from src.domain.logic.admin_data import datasette_app
from src.domain.logic.admin_data.datasette_app import build_datasette

# What the container sees for a request nginx received over HTTPS.
_PROXIED = Request.fake("http://www.bedlamconnect.com/admin/data/-/dashboards/x")


@pytest.mark.parametrize(
    "public_url, scheme",
    [
        ("https://www.bedlamconnect.com", "https://"),
        ("http://localhost:8000", "http://"),
    ],
)
def test_absolute_urls_follow_the_public_scheme(
    admin_db, monkeypatch, public_url, scheme
):
    monkeypatch.setattr(datasette_app.settings, "APP_BASE_URL", public_url)
    ds = build_datasette(str(admin_db))
    url = ds.absolute_url(_PROXIED, ds.urls.instance())
    assert url.startswith(scheme) and url.endswith("/admin/data/")
