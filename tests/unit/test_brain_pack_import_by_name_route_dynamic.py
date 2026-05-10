from __future__ import annotations


def test_import_by_name_route_does_not_require_specific_service_class_name():
    from mozok.api.brain_pack_import_by_name_route import router

    routes = [getattr(route, "path", None) for route in router.routes]
    assert "/brain-packs/import-by-name" in routes
