import { describe, expect, it } from "vitest";
import { project, validateGeometry } from "./geo";

const square = {
  type: "Polygon",
  coordinates: [
    [
      [77.5, 12.9],
      [77.51, 12.9],
      [77.51, 12.91],
      [77.5, 12.91],
      [77.5, 12.9],
    ],
  ],
};

describe("validateGeometry", () => {
  it("accepts closed Polygon and MultiPolygon", () => {
    expect(validateGeometry(square).ok).toBe(true);
    expect(validateGeometry({ type: "MultiPolygon", coordinates: [square.coordinates] }).ok).toBe(
      true,
    );
  });
  it.each([
    ["missing", null],
    ["point", { type: "Point", coordinates: [1, 2] }],
    [
      "unclosed ring",
      {
        type: "Polygon",
        coordinates: [
          [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 1],
          ],
        ],
      },
    ],
    [
      "out of bounds",
      {
        type: "Polygon",
        coordinates: [
          [
            [0, 0],
            [200, 0],
            [200, 1],
            [0, 1],
            [0, 0],
          ],
        ],
      },
    ],
    [
      "not finite",
      {
        type: "Polygon",
        coordinates: [
          [
            [0, 0],
            [NaN, 0],
            [1, 1],
            [0, 1],
            [0, 0],
          ],
        ],
      },
    ],
    ["empty multipolygon", { type: "MultiPolygon", coordinates: [] }],
  ])("rejects %s", (_n, g) => {
    const v = validateGeometry(g as never);
    expect(v.ok).toBe(false);
  });
});

describe("project", () => {
  it("draws valid layers inside the viewport and reports invalid ones without drawing them", () => {
    const p = project(
      [
        { key: "a", geometry: square },
        { key: "bad", geometry: { type: "Point", coordinates: [0, 0] } },
      ],
      400,
      300,
      16,
    );
    expect(p.layers).toHaveLength(1);
    expect(p.invalid).toEqual([{ key: "bad", reason: expect.stringContaining("Unsupported") }]);
    const nums = p.layers[0]!.d.match(/-?\d+\.\d+/g)!.map(Number);
    expect(Math.min(...nums)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...nums)).toBeLessThanOrEqual(400);
  });
  it("returns nothing when no layer is valid", () => {
    expect(project([{ key: "x", geometry: null }]).layers).toEqual([]);
  });
});
