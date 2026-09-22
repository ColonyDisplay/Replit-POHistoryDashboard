#!/usr/bin/env python3
"""Mocked browser regressions for KPI date selection and source labeling."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import po_api


def main():
    from playwright.sync_api import sync_playwright, expect

    subprocess.run(["node", str(ROOT / "scripts/ui-test/build.js")], check=True, cwd=ROOT)
    bundle = Path("/tmp/datalake-ui-bundle.js").read_text()
    styles = "\n".join((ROOT / "next-ui/src/app" / name).read_text()
                       for name in ["globals.css", "App.css", "Kpi.css"])
    latest = "2026-09-17"
    calls = []

    def route_request(route):
        url = urlsplit(route.request.url)
        path = url.path
        if path == "/bundle.js":
            return route.fulfill(content_type="application/javascript", body=bundle)
        if path == "/styles.css":
            return route.fulfill(content_type="text/css", body=styles)
        if path == "/":
            return route.fulfill(content_type="text/html", body=(
                '<meta charset="utf-8"><link rel="stylesheet" href="/styles.css"><div id="root"></div>'
                '<script src="/bundle.js"></script>'
            ))
        if path == "/me":
            body = {"access": True, "sections": ["operations_kpi"], "role": "admin"}
        elif path == "/api/health":
            body = {"state": "ok", "database": "neon", "latestSuccessfulPublish": latest,
                    "lastSuccessAt": "2026-09-18T11:01:04Z"}
        elif path in ("/api/kpis", "/api/kpis/trends"):
            assert route.request.headers.get("authorization") == "Bearer ui-test-token"
            calls.append(path + ("?" + url.query if url.query else ""))
            date = parse_qs(url.query).get("asOf", [latest])[0]
            body = copy.deepcopy(po_api.PREVIEW_KPI_SUMMARY) if path == "/api/kpis" else po_api._preview_kpi_trends()
            body["asOf"] = date
        else:
            return route.fulfill(status=404, body="Not found")
        route.fulfill(content_type="application/json", body=json.dumps(body))

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/*", route_request)
        page.goto("http://kpi.test/")
        page.get_by_role("button", name="Operations KPI").click()
        expect(page.get_by_text("Latest published Neon results", exact=True)).to_be_visible()
        expect(page.locator('input[type="date"]')).to_have_value(latest)
        assert calls[:2] == ["/api/kpis", f"/api/kpis/trends?asOf={latest}"]
        page.locator('input[type="date"]').fill("2026-08-20")
        expect(page.get_by_text("Historical Neon results", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_enabled()
        before = len(calls)
        page.get_by_role("button", name="Refresh", exact=True).click()
        page.wait_for_function("!document.querySelector('.kpi-toolbar button:last-child').disabled")
        assert calls[before:] == ["/api/kpis?asOf=2026-08-20", "/api/kpis/trends?asOf=2026-08-20"]
        page.get_by_role("button", name="Latest available", exact=True).click()
        expect(page.locator('input[type="date"]')).to_have_value(latest)
        expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_enabled()
        page.screenshot(path="/tmp/kpi-desktop.jpg", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path="/tmp/kpi-mobile.jpg", full_page=True)
        page.goto("http://kpi.test/?preview=1")
        page.get_by_role("button", name="Operations KPI").click()
        expect(page.get_by_text("Unsigned sample preview", exact=True)).to_be_visible()
        expect(page.get_by_text("Latest published Neon results", exact=True)).to_have_count(0)
        browser.close()
    print("KPI browser checks passed: latest, pinned trends, historical refresh, preview labels, responsive layout")


if __name__ == "__main__":
    main()