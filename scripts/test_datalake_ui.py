#!/usr/bin/env python3
"""Focused mocked-browser verification for the DataLake reporting UI.

Run separately from pytest:
  .pythonlibs/bin/python scripts/test_datalake_ui.py
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path("/tmp/datalake-ui-bundle.js")
ORIGIN = "http://datalake.test"
HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles.css"></head>
<body><div id="root"></div><script src="/bundle.js"></script></body></html>"""


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    from playwright.sync_api import sync_playwright

    subprocess.run(
        ["node", str(ROOT / "scripts/ui-test/build.js")],
        cwd=ROOT,
        check=True,
    )
    bundle = BUNDLE.read_text()
    styles = "\n".join(
        (ROOT / name).read_text()
        for name in (
            "next-ui/src/app/globals.css",
            "next-ui/src/app/App.css",
            "next-ui/src/app/DataLake.css",
            "next-ui/src/app/Kpi.css",
            "next-ui/src/app/LookupPage.css",
        )
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/repl/tools/bin/chromium",
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(10_000)
        mode = {"name": "admin"}
        calls = []
        attempts = {}

        def api_response(report):
            attempts[report] = attempts.get(report, 0) + 1
            if report == "queries/shipping_logs":
                return 200, {
                    "state": "ok",
                    "data": {
                        "status": "ok",
                        "query": "shipping_logs",
                        "returned": 2,
                        "checked_at": "2026-09-19T15:30:00Z",
                        "rows": [
                            {
                                "Company": "EPIC",
                                "PackNum": 1042,
                                "ShipDate": "2026-09-18",
                                "CustNum": 21,
                                "CustID": "ACME",
                                "PackLine": 1,
                                "OrderNum": 5001,
                                "OrderLine": 1,
                                "PartNum": "PART-A",
                                "OurInventoryShipQty": "12.00",
                            },
                            {
                                "Company": "EPIC",
                                "PackNum": 1043,
                                "ShipDate": "2026-09-19",
                                "CustNum": 22,
                                "CustID": "BETA",
                                "PackLine": 2,
                                "OrderNum": 5002,
                                "OrderLine": 3,
                                "PartNum": "PART-B",
                                "OurInventoryShipQty": "",
                            },
                        ],
                    },
                }
            if report in ("catalog", "tables"):
                return 200, {
                    "state": "ok",
                    "data": {
                        "status": "ok",
                        "count": 2,
                        "by_class": {"scd2": 1, "append": 1, "snapshot": 0},
                        "tables": [
                            {
                                "table": "ShipHead",
                                "class": "scd2",
                                "keys": ["Company", "PackNum"],
                                "ud": False,
                                "watermark": None,
                            },
                            {
                                "table": "ShipDtl",
                                "class": "append",
                                "keys": ["Company", "PackNum", "PackLine"],
                                "ud": False,
                                "watermark": "ShipDate",
                            },
                        ],
                    },
                }
            if report == "queries":
                return 200, {
                    "state": "ok",
                    "data": {
                        "status": "ok",
                        "count": 2,
                        "queries": [
                            {
                                "name": "shipping_logs",
                                "status": "ready",
                                "summary": "Shipment line activity",
                                "tables": ["ShipHead", "ShipDtl", "Customer"],
                            },
                            {
                                "name": "shipping_wow",
                                "status": "ready",
                                "summary": "Weekly shipping comparison",
                                "tables": ["ShipHead", "ShipDtl"],
                            },
                        ],
                    },
                }
            if report == "freshness":
                if attempts[report] == 1:
                    return 502, {
                        "state": "upstream_error",
                        "message": "Freshness source timed out",
                    }
                return 200, {
                    "state": "ok",
                    "data": {
                        "status": "fresh",
                        "latest_snapshot_date": "2026-09-18",
                        "latest_load_date": "2026-09-19",
                        "tables_checked": 75,
                        "checked_at": "2026-09-19T15:30:00Z",
                    },
                }
            if report in ("wow", "mom"):
                weekly = report == "wow"
                return 200, {
                    "state": "ok",
                    "data": {
                        "status": "ok",
                        "period": report,
                        "metrics": [{
                            "this_from": "2026-09-13" if weekly else "2026-09-01",
                            "this_to": "2026-09-19",
                            "prev_from": "2026-09-06" if weekly else "2026-08-01",
                            "prev_to": "2026-09-12" if weekly else "2026-08-31",
                            "qty_this": 120 if weekly else 480,
                            "qty_prev": 100 if weekly else 450,
                            "qty_delta": 20 if weekly else 30,
                        }],
                    },
                }
            raise AssertionError(f"Unexpected report: {report}")

        def route_request(route):
            request = route.request
            path = request.url.removeprefix(ORIGIN)
            if path.startswith("/bundle.js"):
                route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=bundle,
                )
            elif path.startswith("/styles.css"):
                route.fulfill(
                    status=200,
                    content_type="text/css",
                    body=styles,
                )
            elif path.startswith("/me"):
                sections = ["search", "operations_kpi", "datalake"]
                if mode["name"] == "nonadmin":
                    sections = ["search"]
                body = {
                    "access": True,
                    "email": "ui@example.test",
                    "sections": sections,
                    "previewMode": mode["name"] in ("preview", "live-preview"),
                    "liveData": mode["name"] == "live-preview",
                }
                check(
                    request.headers.get("authorization") == "Bearer ui-test-token",
                    "/me did not use the test token getter",
                )
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(body),
                )
            elif path.startswith("/api/datalake/"):
                check(
                    request.headers.get("authorization") == "Bearer ui-test-token",
                    "DataLake request did not retain browser Clerk authentication",
                )
                calls.append(request.url)
                report = path.split("/api/datalake/", 1)[1].split("?", 1)[0]
                status, body = api_response(report)
                route.fulfill(
                    status=status,
                    content_type="application/json",
                    body=json.dumps(body),
                )
            else:
                route.fulfill(status=200, content_type="text/html", body=HTML)

        page.route("**/*", route_request)

        # Admin home exposes the privileged destination.
        page.goto(f"{ORIGIN}/?page=home")
        page.get_by_role(
            "heading", name="What would you like to work on?"
        ).wait_for()
        check(
            page.get_by_role("button", name="DataLake").count() == 1,
            "Admin home did not expose its DataLake link",
        )

        # Shipping Logs is the only report requested on initial entry.
        calls.clear()
        attempts.clear()
        page.goto(f"{ORIGIN}/datalake?page=datalake")
        page.get_by_role("heading", name="Shipping logs").wait_for()
        page.get_by_role("cell", name="1042 EPIC").wait_for()
        check(
            [url.split("/api/datalake/", 1)[1] for url in calls]
            == ["queries/shipping_logs"],
            f"Initial report requests were not shipping-only: {calls}",
        )
        for heading in (
            "Pack #",
            "Ship date",
            "Customer",
            "Part",
            "Order",
            "Ship qty",
        ):
            check(
                page.get_by_role("columnheader", name=heading).count() == 1,
                f"Missing shipping column: {heading}",
            )
        check(
            page.locator(".lake-json").count() == 0,
            "DataLake success output still uses raw JSON",
        )
        second_row = page.locator("table.lake-shipping-table tbody tr").nth(1)
        check(
            second_row.locator("td").last.inner_text() == "—",
            "Blank shipment quantity was rendered as a numeric zero",
        )
        shipping_surface = page.locator("section.lake-surface").first
        label_id = shipping_surface.get_attribute("aria-labelledby")
        check(
            label_id == "shipping-title"
            and page.locator(f"#{label_id}").count() == 1,
            "Shipping report region does not reference a real heading",
        )

        # Standard tab keyboard navigation selects and focuses the next report.
        shipping_tab = page.get_by_role("tab", name="Shipping logs")
        catalog_tab = page.get_by_role("tab", name="Catalog")
        check(
            shipping_tab.get_attribute("tabindex") == "0"
            and catalog_tab.get_attribute("tabindex") == "-1",
            "Tabs do not use a single roving tab stop",
        )
        shipping_tab.focus()
        page.keyboard.press("ArrowRight")
        check(
            catalog_tab.get_attribute("aria-selected") == "true"
            and catalog_tab.get_attribute("tabindex") == "0"
            and page.evaluate("document.activeElement?.id") == "lake-tab-catalog",
            "ArrowRight did not select and focus the Catalog tab",
        )

        # Catalog and table views load only when selected.
        page.get_by_role("heading", name="Available queries").wait_for()
        page.get_by_role("heading", name="shipping_logs").wait_for()
        check(
            any("/api/datalake/catalog" in url for url in calls)
            and any("/api/datalake/queries" in url for url in calls),
            "Catalog did not load catalog and query registries",
        )

        page.get_by_role("tab", name="Tables").click()
        page.get_by_role("cell", name="ShipHead").wait_for()
        check(
            any("/api/datalake/tables" in url for url in calls),
            "Tables tab did not request its registry",
        )

        # Failure state is actionable and retry recovers the same report.
        page.get_by_role("tab", name="Freshness").click()
        page.get_by_text("Freshness source timed out").wait_for()
        page.get_by_role("button", name="Retry report").click()
        page.get_by_text("2026-09-18").wait_for()
        check(
            attempts.get("freshness") == 2,
            "Freshness retry did not make exactly one new request",
        )

        # Confirmed period routes render report cards instead of JSON.
        page.get_by_role("tab", name="Period comparisons").click()
        page.get_by_role("heading", name="Week over week").wait_for()
        page.get_by_role("heading", name="Month over month").wait_for()
        page.get_by_text("+20", exact=True).wait_for()
        page.get_by_text("+30", exact=True).wait_for()
        check(
            any("/api/datalake/wow" in url for url in calls)
            and any("/api/datalake/mom" in url for url in calls),
            "Period comparison routes were not requested",
        )
        check(
            not any("/api/datalake/health" in url for url in calls),
            "The old Health report still loads by default",
        )

        page.screenshot(path="/tmp/datalake-admin-ui.png", full_page=True)
        page.locator(".datalake-home-link").click()
        page.get_by_role(
            "heading", name="What would you like to work on?"
        ).wait_for()

        # A direct non-admin visit is denied before any report request.
        mode["name"] = "nonadmin"
        calls.clear()
        page.goto(f"{ORIGIN}/datalake?page=datalake")
        page.get_by_role("heading", name="DataLake access is restricted").wait_for()
        check(not calls, "Non-admin direct visit made DataLake requests")

        # Sample Preview never substitutes fictional DataLake rows.
        mode["name"] = "preview"
        calls.clear()
        page.goto(f"{ORIGIN}/datalake?page=datalake&preview=1")
        page.get_by_text("Preview · No live data", exact=True).wait_for()
        page.get_by_text("does not substitute fictional rows", exact=False).wait_for()
        check(not calls, "Sample Preview made protected DataLake requests")
        check(
            page.get_by_role("table").count() == 0,
            "Sample Preview rendered a fictional DataLake table",
        )

        # Live Preview uses the same real same-origin API path.
        mode["name"] = "live-preview"
        calls.clear()
        attempts.clear()
        page.goto(f"{ORIGIN}/datalake?page=datalake&preview=1")
        page.get_by_role("cell", name="1042 EPIC").wait_for()
        check(
            any("/api/datalake/queries/shipping_logs" in url for url in calls),
            "Live Preview did not load Shipping Logs",
        )
        check(
            page.get_by_text("Preview · No live data", exact=True).count() == 0,
            "Live Preview was mislabeled as sample-only",
        )

        # The wide operational table is contained on a phone viewport.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{ORIGIN}/datalake?page=datalake&preview=1")
        page.get_by_role("cell", name="1042 EPIC").wait_for()
        check(
            page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            "Shipping table caused page-level horizontal overflow",
        )
        page.screenshot(path="/tmp/datalake-mobile-ui.png", full_page=True)

        browser.close()

    print("DataLake UI browser verification passed")
    print("Screenshots: /tmp/datalake-admin-ui.png, /tmp/datalake-mobile-ui.png")


if __name__ == "__main__":
    main()