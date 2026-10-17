import { project, type Layer } from "@/lib/geo";

const COLORS = ["var(--primary)", "var(--warning)", "var(--success)"];

/**
 * Dependency-free SVG viewer for stored GeoJSON (EPSG:4326). No basemap or imagery is drawn: the
 * view is a schematic of the stored geometry only, and says so. Invalid geometry is reported, not
 * drawn or repaired.
 */
export function GeometryView({
  layers,
  label,
}: {
  layers: Array<Layer & { name: string }>;
  label: string;
}) {
  const p = project(layers);
  const names = new Map(layers.map((l) => [l.key, l.name]));
  return (
    <figure>
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${p.width} ${p.height}`}
        className="bg-background w-full rounded-md border"
      >
        {p.layers.map((l, i) => (
          <path
            key={l.key}
            d={l.d}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.25}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            fillRule="evenodd"
          />
        ))}
      </svg>
      <figcaption className="text-muted-foreground mt-2 space-y-1 text-xs">
        <p>Schematic of stored geometry, EPSG:4326. Not an imagery or map view.</p>
        {p.layers.length > 0 && (
          <ul className="flex flex-wrap gap-x-3">
            {p.layers.map((l, i) => (
              <li key={l.key}>
                <span aria-hidden style={{ color: COLORS[i % COLORS.length] }}>
                  ■{" "}
                </span>
                {names.get(l.key)}
              </li>
            ))}
          </ul>
        )}
        {p.invalid.map((i) => (
          <p key={i.key} role="alert" className="text-destructive">
            {names.get(i.key)} not drawn: {i.reason}
          </p>
        ))}
      </figcaption>
    </figure>
  );
}
