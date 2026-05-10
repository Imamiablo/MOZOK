from __future__ import annotations


def test_import_by_name_route_is_registered_in_openapi():
    from mozok.api.main import app

    schema = app.openapi()
    assert "/brain-packs/import-by-name" in schema["paths"]
    assert "post" in schema["paths"]["/brain-packs/import-by-name"]
