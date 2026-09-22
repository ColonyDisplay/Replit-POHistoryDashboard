export function formatKpiValue(value, unit = "", label = "") {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);

  const money = /\$|usd|dollar/i.test(`${unit} ${label}`);
  const perEach = /\/\s*ea/i.test(unit);
  const maximumFractionDigits = perEach ? 2 : money ? 0 : Math.abs(number) < 10 && number % 1 ? 2 : 1;
  const formatted = new Intl.NumberFormat("en-US", {
    style: money ? "currency" : "decimal",
    currency: money ? "USD" : undefined,
    maximumFractionDigits,
  }).format(number);
  return perEach ? `${formatted}/EA` : formatted;
}

export function formatBusinessDate(value) {
  if (!value) return "Unavailable";
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

export function priorBusinessDayCentral() {
  const centralDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const [year, month, day] = centralDate.split("-").map(Number);
  const result = new Date(Date.UTC(year, month - 1, day));
  do {
    result.setUTCDate(result.getUTCDate() - 1);
  } while (result.getUTCDay() === 0 || result.getUTCDay() === 6);
  return result.toISOString().slice(0, 10);
}