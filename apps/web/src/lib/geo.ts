import type { GeoJsonGeometry } from "@/lib/api/endpoints";

/**
 * Geometry helpers for the SVG viewer. All stored geometry is GeoJSON in EPSG:4326
 * (lon, lat) per ADR-0012. Nothing here fabricates or repairs geometry: invalid input is reported
 * as invalid and is not drawn.
 */
export type Ring = Array<[number, number]>;
export type Validation = { ok: true; polygons: Ring[][] } | { ok: false; reason: string };

function validRing(ring: unknown): ring is Ring {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  for (const p of ring) {
    if (!Array.isArray(p) || p.length < 2) return false;
    const [lon, lat] = p as number[];
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return false;
    if (Math.abs(lon as number) > 180 || Math.abs(lat as number) > 90) return false;
  }
  const first = ring[0] as number[];
  const last = ring[ring.length - 1] as number[];
  return first[0] === last[0] && first[1] === last[1];
}

export function validateGeometry(geometry: GeoJsonGeometry | null | undefined): Validation {
  if (!geometry || typeof geometry !== "object")
    return { ok: false, reason: "No geometry stored." };
  const coords = geometry.coordinates as unknown;
  let polygons: unknown[];
  if (geometry.type === "Polygon") polygons = [coords];
  else if (geometry.type === "MultiPolygon" && Array.isArray(coords)) polygons = coords;
  else return { ok: false, reason: `Unsupported geometry type "${String(geometry.type)}".` };
  if (polygons.length === 0) return { ok: false, reason: "Geometry is empty." };
  for (const poly of polygons) {
    if (!Array.isArray(poly) || poly.length === 0 || !poly.every(validRing)) {
      return {
        ok: false,
        reason: "Geometry is malformed (rings must be closed, finite and within lon/lat bounds).",
      };
    }
  }
  return { ok: true, polygons: polygons as Ring[][] };
}

export interface Layer {
  key: string;
  geometry: GeoJsonGeometry | null | undefined;
}
export interface DrawnLayer {
  key: string;
  d: string;
}
export interface Projection {
  layers: DrawnLayer[];
  invalid: Array<{ key: string; reason: string }>;
  width: number;
  height: number;
}

/** Equirectangular projection fitted to all valid layers (cos-latitude corrected). */
export function project(layers: Layer[], width = 400, height = 300, pad = 16): Projection {
  const valid: Array<{ key: string; polygons: Ring[][] }> = [];
  const invalid: Projection["invalid"] = [];
  for (const layer of layers) {
    const v = validateGeometry(layer.geometry);
    if (v.ok) valid.push({ key: layer.key, polygons: v.polygons });
    else invalid.push({ key: layer.key, reason: v.reason });
  }
  const all = valid.flatMap((l) => l.polygons.flatMap((poly) => poly.flat()));
  if (all.length === 0) return { layers: [], invalid, width, height };
  const lons = all.map((p) => p[0]);
  const lats = all.map((p) => p[1]);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const k = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180) || 1;
  const spanX = Math.max((maxLon - minLon) * k, 1e-9);
  const spanY = Math.max(maxLat - minLat, 1e-9);
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const offX = (width - spanX * scale) / 2;
  const offY = (height - spanY * scale) / 2;
  const toXY = ([lon, lat]: [number, number]) =>
    `${(offX + (lon - minLon) * k * scale).toFixed(2)},${(offY + (maxLat - lat) * scale).toFixed(2)}`;
  return {
    layers: valid.map((l) => ({
      key: l.key,
      d: l.polygons.flatMap((poly) => poly.map((ring) => `M${ring.map(toXY).join("L")}Z`)).join(""),
    })),
    invalid,
    width,
    height,
  };
}
