import {
  Activity,
  ClipboardList,
  FolderKanban,
  LayoutDashboard,
  Map,
  ScrollText,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown when the caller holds ANY of these permissions. */
  anyOf: string[];
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    anyOf: ["candidate:read", "case:read"],
  },
  { href: "/candidates", label: "Candidates", icon: ClipboardList, anyOf: ["candidate:read"] },
  { href: "/cases", label: "Inspection cases", icon: FolderKanban, anyOf: ["case:read"] },
  {
    href: "/parcels",
    label: "Parcels & properties",
    icon: Map,
    anyOf: ["parcel:read", "property:read"],
  },
  { href: "/permits", label: "Permits", icon: ScrollText, anyOf: ["permit:read"] },
  {
    href: "/activity",
    label: "Activity",
    icon: Activity,
    anyOf: ["candidate:read", "case:read", "permit:read", "parcel:read"],
  },
];

const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  candidates: "Candidates",
  cases: "Inspection cases",
  parcels: "Parcels & properties",
  permits: "Permits",
  activity: "Activity",
  system: "System status",
};

export function breadcrumbsFor(pathname: string): Array<{ href: string; label: string }> {
  const parts = pathname.split("/").filter(Boolean);
  return parts.map((part, i) => ({
    href: `/${parts.slice(0, i + 1).join("/")}`,
    label: SEGMENT_LABELS[part] ?? `${part.slice(0, 8)}`,
  }));
}
