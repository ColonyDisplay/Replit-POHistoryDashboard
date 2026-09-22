import assert from "node:assert/strict";

export const KPI_AS_OF = "2026-08-20";

const SECTION_DEFINITIONS = [
  {
    id: "shipping",
    title: "Shipping",
    metrics: [
      ["SH-01", "Units shipped", "EA", 2411, 22623, 2384],
      ["SH-02", "Shipping revenue", "USD", 343988, 5985720, 342938],
      ["SH-03", "Pallets shipped", "PLT", 49, 263, 40],
    ],
  },
  {
    id: "receiving",
    title: "Receiving",
    metrics: [
      ["RC-01", "Units received", "EA", 10968, 267403, 6675],
      ["RC-02", "Received standard cost", "USD", 4632, 941319, 36198],
      ["RC-04", "Received actual cost", "USD", 16572, 1174091, 35930],
      ["RC-05", "Purchase price variance", "USD", 11941, 232772, -268],
    ],
  },
  {
    id: "inventory",
    title: "Inventory",
    metrics: [
      ["IV-02", "Cycle counts completed", "count", 18, 244, 16],
      ["IV-05-USD", "Finished goods value", "USD", 1438340, 1438340, 1440598],
      ["IV-04-USD", "Work in process value", "USD", 4379469, 4379469, 4332118],
      ["IV-03-USD", "Raw material value", "USD", 2522846, 2522846, 2543832],
    ],
  },
  {
    id: "fabrication",
    title: "Fabrication",
    metrics: [
      ["FAB-01", "Fabrication output", "EA", 142, 2450, 135],
      ["FAB-02", "Fabrication hours", "hours", 388, 6280, 402],
      ["FAB-04", "First-pass yield", "percent", 97.8, 97.2, 97.1],
      ["FAB-05", "Scrap value", "USD", 2180, 31750, 2440],
    ],
  },
  {
    id: "assembly",
    title: "Assembly",
    metrics: [
      ["ASM-01", "Assembly output", "EA", 96, 1684, 90],
      ["ASM-02", "Assembly hours", "hours", 246, 4228, 254],
      ["KIT-01", "Kits completed", "count", 41, 706, 37],
      ["KIT-02", "Kit shortages", "count", 3, 42, 5],
    ],
  },
];

const sections = SECTION_DEFINITIONS.map((section) => ({
  id: section.id,
  title: section.title,
  metrics: section.metrics.map(([id, label, unit, daily, mtd, avg7]) => ({
    id,
    label,
    unit,
    daily,
    mtd,
    avg7,
    status: "ok",
    subsection: "Published activity",
  })),
}));

const allMetrics = sections.flatMap((section) => (
  section.metrics.map((metric) => ({ sectionId: section.id, ...metric }))
));

function dailySeries(value) {
  const end = new Date(`${KPI_AS_OF}T00:00:00Z`);
  return Array.from({ length: 30 }, (_, index) => {
    const date = new Date(end);
    date.setUTCDate(end.getUTCDate() - (29 - index));
    const factor = 0.86 + ((index * 7) % 13) / 50;
    return {
      date: date.toISOString().slice(0, 10),
      value: Number((value * factor).toFixed(2)),
    };
  });
}

function monthlySeries(value) {
  const periods = [
    [2025, 9, "Sep 25"], [2025, 10, "Oct 25"], [2025, 11, "Nov 25"],
    [2025, 12, "Dec 25"], [2026, 1, "Jan 26"], [2026, 2, "Feb 26"],
    [2026, 3, "Mar 26"], [2026, 4, "Apr 26"], [2026, 5, "May 26"],
    [2026, 6, "Jun 26"], [2026, 7, "Jul 26"], [2026, 8, "Aug 26"],
  ];
  return periods.map(([year, month, label], index) => ({
    year,
    month,
    label,
    value: Number((value * (0.78 + index * 0.025)).toFixed(2)),
  }));
}

export const KPI_SUMMARY = {
  asOf: KPI_AS_OF,
  historyEnabled: true,
  sections,
};

export const KPI_TRENDS = {
  asOf: KPI_AS_OF,
  historyEnabled: true,
  metrics: Object.fromEntries(allMetrics.map((metric) => [
    metric.id,
    {
      id: metric.id,
      label: metric.label,
      unit: metric.unit,
      sectionId: metric.sectionId,
      grain: "daily_activity",
      fromHistory: false,
      dailyLast30: dailySeries(metric.daily),
      monthlyTrailing12: monthlySeries(metric.mtd),
    },
  ])),
};

export const KPI_HEALTH = {
  status: "ok",
  state: "ok",
  database: "neon",
  databaseStatus: "connected",
  appVersion: "visual-fixture",
  latestSuccessfulPublish: KPI_AS_OF,
  lastSuccessAt: "2026-08-20T14:30:00Z",
  expectedBusinessDate: KPI_AS_OF,
  failures7d: 0,
};

export const KPI_DETAIL = {
  metricId: "SH-01",
  label: "Units shipped",
  unit: "EA",
  period: KPI_AS_OF,
  rangeStart: KPI_AS_OF,
  rangeEnd: KPI_AS_OF,
  rowCount: 3,
  totals: { qty: 2411, dollars: null },
  rows: [
    { work_center: "Shipping", reference: "SO-10481", quantity: 908, status: "Complete" },
    { work_center: "Shipping", reference: "SO-10482", quantity: 816, status: "Complete" },
    { work_center: "Shipping", reference: "SO-10483", quantity: 687, status: "Complete" },
  ],
};

function assertOnlyKeys(value, allowed, label) {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  assert.deepEqual(extras, [], `${label} contains unapproved fields: ${extras.join(", ")}`);
}

assertOnlyKeys(KPI_SUMMARY, ["asOf", "historyEnabled", "sections"], "KPI summary");
KPI_SUMMARY.sections.forEach((section) => {
  assertOnlyKeys(section, ["id", "title", "metrics"], `KPI section ${section.id}`);
  section.metrics.forEach((metric) => {
    assertOnlyKeys(
      metric,
      ["id", "label", "unit", "daily", "mtd", "avg7", "status", "note", "subsection"],
      `KPI metric ${metric.id}`,
    );
  });
});
assertOnlyKeys(KPI_TRENDS, ["asOf", "historyEnabled", "metrics"], "KPI trends");
Object.values(KPI_TRENDS.metrics).forEach((metric) => {
  assertOnlyKeys(
    metric,
    [
      "id", "label", "unit", "sectionId", "grain", "fromHistory",
      "dailyLast30", "monthlyTrailing12",
    ],
    `KPI trend ${metric.id}`,
  );
  metric.dailyLast30.forEach((point) => assertOnlyKeys(point, ["date", "value"], "Daily trend point"));
  metric.monthlyTrailing12.forEach((point) => (
    assertOnlyKeys(point, ["year", "month", "label", "value"], "Monthly trend point")
  ));
});
assertOnlyKeys(
  KPI_HEALTH,
  [
    "status", "state", "database", "databaseStatus", "appVersion",
    "latestSuccessfulPublish", "lastSuccessAt", "expectedBusinessDate", "failures7d",
  ],
  "KPI health",
);
assertOnlyKeys(
  KPI_DETAIL,
  ["metricId", "label", "unit", "period", "rangeStart", "rangeEnd", "rowCount", "totals", "rows"],
  "KPI detail",
);