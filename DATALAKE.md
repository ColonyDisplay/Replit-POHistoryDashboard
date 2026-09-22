# DataLake reporting

DataLake is part of the existing Colony Epicor Dashboard. It uses the dashboard's
Clerk session, role grants, Next.js static export, and FastAPI host. It does not
create or publish a separate application.

## Access and navigation

Only active users with the `admin` role receive the `datalake` section from
`/me`. Authorized admins can open the DataLake card or visit `/datalake`
directly. Every `/api/datalake/*` request independently enforces:

1. a valid Clerk session,
2. the approved email domain,
3. an active application membership,
4. the admin-only `datalake` section, and
5. a real session or the development-only trusted live Preview session.

Other production roles cannot load the page's reports. Sample Preview does not
request protected lake data and does not display fictional DataLake rows.
Development Preview may load live read-only reports only when both
`PREVIEW_ADMIN_MODE=1` and `PREVIEW_LIVE_DATA=1` are enabled. That exception is
disabled on deployments.

## Report UI

Shipping Logs is the default report. It renders the approved
`shipping_logs` result as an HTML table with shipment, customer, part, order, and
quantity columns. DataLake success responses are not displayed as raw JSON.

Additional tabs load only when selected:

- **Catalog** — table-class totals and the registered query directory.
- **Tables** — table names, classes, keys, and watermarks.
- **Freshness** — latest snapshot/load dates and source check metadata.
- **Period comparisons** — confirmed week-over-week and month-over-month
  shipping quantity cards.

No value is estimated or substituted by the portal.

## Confirmed same-origin API

All browser requests are GET requests under `/api/datalake`. The server maps
only the following reviewed paths to `LAKE_API_BASE_URL`:

| Browser endpoint | Upstream path | Allowed query parameters |
| --- | --- | --- |
| `/api/datalake/health` | `/health` | None |
| `/api/datalake/freshness` | `/freshness` | None |
| `/api/datalake/catalog` | `/catalog` | None |
| `/api/datalake/tables` | `/tables` | None |
| `/api/datalake/queries` | `/queries` | None |
| `/api/datalake/queries/{name}` | `/queries/{name}` | Per-query allowlist |
| `/api/datalake/current/{table}` | `/current/{table}` | `limit` |
| `/api/datalake/pit/{table}` | `/pit/{table}` | Required `as_of`; optional `limit` |
| `/api/datalake/wow` | `/wow` | `as_of`, `limit` |
| `/api/datalake/mom` | `/mom` | `as_of`, `limit` |
| `/api/datalake/as-of` | `/as-of` | Required `table`, `as_of`; optional `limit` |

The approved query names are `shipping_as_of`, `shipping_dod`,
`shipping_logs`, `shipping_mom`, and `shipping_wow`. Table identifiers are
restricted to the reviewed catalog returned by the service. Identifiers cannot
contain path separators or arbitrary URL content.

Dates must be real, non-future `YYYY-MM-DD` values. Limits are integers from
1 through 500. Duplicate, unknown, or out-of-range parameters are rejected
before an upstream request is made. `from` cannot be later than `to`.

Report responses use `{state, message, data}`. States include `ok`, `empty`,
`unavailable`, `not_configured`, `upstream_error`, and `invalid_request`.
Authentication failures retain the dashboard's `detail` response format.
Responses include `Cache-Control: no-store`.

## Credential boundary

The browser authenticates to the same-origin FastAPI routes with its Clerk
session token. The server never forwards that Authorization header, Clerk
cookies, Clerk secret headers, or arbitrary browser headers upstream.

For each upstream request, the server creates a new header set containing only:

- `Accept: application/json`
- the fixed DataLake user agent
- `Authorization: Bearer LAKE_API_AUTH_TOKEN`

`LAKE_API_BASE_URL` and `LAKE_API_AUTH_TOKEN` are read only from the server
environment. There is no source-code URL fallback and no gateway-token fallback.
`MCP_GATEWAY_AUTH_TOKEN` must not be used for DataLake. Lake or object-storage
credentials must never be placed in frontend variables, build output, logs,
screenshots, or chat.

The destination validator accepts only HTTPS under the reviewed lake-api service
tree on the approved host. User information, nonstandard ports, query strings,
fragments, encoded paths, traversal, redirects, inherited proxy settings, and
netrc credentials are rejected. Responses have bounded timeouts and size,
must be finite JSON, and are projected to approved fields. Registered shipping
queries use explicit nested row projections. Current, PIT, and as-of table
routes return reviewed report metadata only; their unreviewed row bodies and
free-form upstream notes are not exposed to the browser.

## Verified contracts

Live server-side probes on September 19, 2026 confirmed:

- `shipping_logs` returns shipment rows with `Company`, `PackNum`, `ShipDate`,
  `CustNum`, `CustID`, `PackLine`, `OrderNum`, `OrderLine`, `PartNum`, and
  `OurInventoryShipQty`;
- Catalog and Tables return the current 75-table registry;
- Queries returns the five approved shipping query definitions;
- Freshness, `/wow`, and `/mom` return successful approved data;
- Current and PIT table endpoints return reviewed table/report metadata; and
- `/as-of` requires `table` and `as_of`.

These checks confirmed route and payload shapes without logging credentials or
row contents.

## Verification

Run:

```text
python -m pytest -q
npm run build --prefix next-ui
python scripts/test_datalake_ui.py
```

The API suite covers access control, route and identifier allowlists, query
validation, credential substitution, response projection, error sanitization,
Preview safeguards, and direct page routes. The browser script bundles the real
UI and uses test-only same-origin responses to verify the shipping table, tabs,
retry states, role denial, no fictional sample data, and mobile containment.