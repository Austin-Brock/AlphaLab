const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usdWhole = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
const dateTime = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });

export function money(value: number | string, { whole = false } = {}): string {
  return (whole ? usdWhole : usd).format(Number(value));
}

export function signedMoney(value: number): string {
  const formatted = money(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `−${formatted}`;
  return formatted;
}

export function percent(fraction: number, { signed = false, digits = 2 } = {}): string {
  const text = `${(Math.abs(fraction) * 100).toFixed(digits)}%`;
  // Values that round to zero get no sign, so a tiny loss doesn't read as "−0.00%".
  if (Number(text.slice(0, -1)) === 0) return text;
  if (fraction < 0) return `−${text}`;
  return signed ? `+${text}` : text;
}

export function quantity(value: string | number): string {
  return number.format(Number(value));
}

export function when(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function duration(startIso: string, endIso: string | null): string {
  if (!endIso) return "—";
  const seconds = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
  return seconds < 60 ? `${seconds.toFixed(1)}s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function tone(value: number): "up" | "down" | "flat" {
  return value > 0 ? "up" : value < 0 ? "down" : "flat";
}

const dayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** "2026-10-21" → "Oct 21". Dates are trading days, so no timezone shifting. */
export function day(isoDate: string): string {
  return dayFormat.format(new Date(`${isoDate}T00:00:00Z`));
}

/** Axis labels like "$1.005M", with just enough decimals to tell ticks `step` apart. */
export function axisMoney(value: number, step: number): string {
  const [unit, suffix] = Math.abs(value) >= 1e6 ? [1e6, "M"] : Math.abs(value) >= 1e3 ? [1e3, "K"] : [1, ""];
  const scaled = step / unit;
  let digits = 0;
  while (digits < 4 && Math.abs(Math.round(scaled * 10 ** digits) - scaled * 10 ** digits) > 1e-9) digits++;
  return `$${(value / unit).toFixed(digits)}${suffix}`;
}
