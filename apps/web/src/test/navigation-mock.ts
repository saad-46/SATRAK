import { vi } from "vitest";

/** Mutable stand-in for next/navigation state, shared by tests via vi.mock. */
export const nav = {
  pathname: "/",
  search: new URLSearchParams(),
  push: vi.fn(),
  replace: vi.fn((url: string) => {
    const q = url.includes("?") ? url.split("?")[1]! : "";
    nav.search = new URLSearchParams(q);
  }),
};
export function resetNav(pathname = "/", search = "") {
  nav.pathname = pathname;
  nav.search = new URLSearchParams(search);
  nav.push.mockClear();
  nav.replace.mockClear();
}
export const useRouter = () => ({
  push: nav.push,
  replace: nav.replace,
  back: vi.fn(),
  prefetch: vi.fn(),
});
export const usePathname = () => nav.pathname;
export const useSearchParams = () => nav.search;
