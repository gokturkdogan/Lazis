export interface StatusRow {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "danger" | "muted";
  mono?: boolean;
}
