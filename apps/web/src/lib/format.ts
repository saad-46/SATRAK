const dateFmt = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : dateFmt.format(d);
}
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : `${dateTimeFmt.format(d)} UTC`;
}
export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}
export function formatArea(sqm: number | null | undefined): string {
  return typeof sqm === "number" ? `${Math.round(sqm).toLocaleString("en-GB")} m²` : "—";
}
/** Model confidence is a score the model emitted, not a probability of a violation. */
export function formatConfidence(value: number | null | undefined): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "not provided";
}
export function humanize(value: string): string {
  const t = value.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
