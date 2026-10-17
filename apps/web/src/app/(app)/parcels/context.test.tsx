import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { footprint, page } from "@/test/fixtures";
import { resetNav } from "@/test/navigation-mock";
import { asUser, FULL_PERMS, J1, renderWithClient, resolved } from "@/test/utils";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import ParcelDetail from "./[id]/page";
import ParcelsPage from "./page";
import PermitsPage from "../permits/page";
import PermitDetail from "../permits/[id]/page";

const PID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const parcel = {
  id: PID,
  jurisdiction_id: J1,
  code: "PCL-001",
  current_version: 2,
  area_sq_m: 500,
  topology_status: "overlaps_neighbour" as const,
  topology_detail: {},
  geometry: footprint,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-02-01T00:00:00Z",
};
const permit = (over = {}) => ({
  id: "p1",
  jurisdiction_id: J1,
  permit_number: "BP-1",
  status: "approved",
  valid_from: "2025-01-01",
  valid_to: null,
  sanctioned_floors: 2,
  sanctioned_footprint_area_sq_m: 100,
  sanctioned_built_up_area_sq_m: null,
  declared_plot_area_sq_m: null,
  declared_parcel_code: "PCL-001",
  parcel_id: PID,
  match_status: "matched" as const,
  match_detail: {},
  source_system: "sys",
  source_record_ref: null,
  is_simulated: false,
  version: 1,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  ...over,
});

beforeEach(() => {
  resetNav("/parcels");
  asUser(FULL_PERMS);
});
afterEach(() => vi.restoreAllMocks());

describe("parcel and permit context", () => {
  it("lists parcels with a topology data-quality flag", async () => {
    vi.spyOn(consoleApi, "parcels").mockResolvedValue(page([parcel]));
    renderWithClient(<ParcelsPage />);
    expect(
      await screen.findByText("Overlaps a neighbour", { selector: "span" }),
    ).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
  });

  it("shows parcel geometry versions and linked records", async () => {
    vi.spyOn(consoleApi, "parcel").mockResolvedValue(parcel);
    vi.spyOn(consoleApi, "parcelVersions").mockResolvedValue([
      {
        version: 1,
        area_sq_m: 480,
        topology_status: "clean",
        topology_detail: {},
        reason: "initial",
        recorded_by: "u1",
        created_at: "2026-01-01T00:00:00Z",
        geometry: footprint,
      },
      {
        version: 2,
        area_sq_m: 500,
        topology_status: "overlaps_neighbour",
        topology_detail: {},
        reason: "resurvey",
        recorded_by: "u1",
        created_at: "2026-02-01T00:00:00Z",
        geometry: footprint,
      },
    ]);
    vi.spyOn(consoleApi, "properties").mockResolvedValue(page([]));
    vi.spyOn(consoleApi, "permits").mockResolvedValue(page([permit()]));
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(page([]));
    vi.spyOn(consoleApi, "cases").mockResolvedValue(page([]));
    renderWithClient(<ParcelDetail params={resolved({ id: PID })} />);
    expect(await screen.findByText("resurvey")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /boundary of parcel PCL-001/i })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "BP-1" })).toBeInTheDocument();
    expect(await screen.findByText("No properties linked")).toBeInTheDocument();
  });

  it("does not request data the role cannot read", async () => {
    asUser({ "parcel:read": [J1] });
    vi.spyOn(consoleApi, "parcel").mockResolvedValue(parcel);
    vi.spyOn(consoleApi, "parcelVersions").mockResolvedValue([]);
    const permits = vi.spyOn(consoleApi, "permits");
    const candidates = vi.spyOn(consoleApi, "candidates");
    renderWithClient(<ParcelDetail params={resolved({ id: PID })} />);
    await screen.findByText("No geometry history");
    expect(permits).not.toHaveBeenCalled();
    expect(candidates).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Permits" })).not.toBeInTheDocument();
  });

  it("distinguishes matched, unmatched and conflicting permits without implying a violation", async () => {
    resetNav("/permits");
    vi.spyOn(consoleApi, "permits").mockResolvedValue(
      page([
        permit(),
        permit({ id: "p2", permit_number: "BP-2", match_status: "unmatched", parcel_id: null }),
        permit({ id: "p3", permit_number: "BP-3", match_status: "conflict", is_simulated: true }),
      ]),
    );
    renderWithClient(<PermitsPage />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Matched to parcel")).toBeInTheDocument();
    expect(within(table).getByText("Unmatched")).toBeInTheDocument();
    expect(within(table).getByText("Match conflict")).toBeInTheDocument();
    expect(within(table).getByText("Simulated data")).toBeInTheDocument();
    expect(
      screen.getByText(/never treated here as evidence that construction is unauthorised/i),
    ).toBeInTheDocument();
  });

  it("explains an unmatched permit as a data gap on its detail page", async () => {
    vi.spyOn(consoleApi, "permit").mockResolvedValue(
      permit({ match_status: "unmatched", parcel_id: null }),
    );
    vi.spyOn(consoleApi, "permitHistory").mockResolvedValue([
      { event: "created", reason: "import", created_at: "2025-01-01T00:00:00Z" },
    ]);
    renderWithClient(<PermitDetail params={resolved({ id: "p1" })} />);
    expect(await screen.findByText(/data gap, not evidence of a violation/i)).toBeInTheDocument();
    expect(await screen.findByText("Created")).toBeInTheDocument();
  });
});
