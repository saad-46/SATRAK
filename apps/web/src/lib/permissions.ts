import type { Me } from "@/lib/api/endpoints";

export function can(me: Me | undefined, permission: string, jurisdictionId?: string): boolean {
  const grants = me?.permissions[permission];
  if (!grants || grants.length === 0) return false;
  return jurisdictionId ? grants.includes(jurisdictionId) : true;
}
export function canAny(me: Me | undefined, permissions: string[]): boolean {
  return permissions.some((p) => can(me, p));
}
export function jurisdictionName(me: Me | undefined, id: string): string {
  const j = me?.jurisdictions.find((x) => x.id === id);
  return j ? j.name : `Jurisdiction ${id.slice(0, 8)}`;
}
