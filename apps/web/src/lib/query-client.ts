import { QueryClient, isServer } from "@tanstack/react-query";

/**
 * QueryClient factory with sane defaults for a data-heavy dashboard app.
 * A fresh client is created per-request on the server (avoiding cross-request
 * state leakage) and a singleton is reused in the browser.
 */
function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000, // 1 min: avoid refetch storms on navigation
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

export function getQueryClient(): QueryClient {
  if (isServer) {
    return makeQueryClient();
  }
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}
