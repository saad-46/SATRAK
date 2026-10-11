"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { onUnauthorized } from "@/lib/api/client";
import { consoleApi, type Me } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { clearToken, getToken, subscribeToken } from "@/lib/auth/token-source";
import { can as canPermission } from "@/lib/permissions";

export type SessionStatus =
  "signed-out" | "expired" | "loading" | "authenticated" | "no-access" | "forbidden" | "error";

interface Session {
  status: SessionStatus;
  me: Me | undefined;
  error: unknown;
  can: (permission: string, jurisdictionId?: string) => boolean;
  signOut: () => void;
  retry: () => void;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const token = useSyncExternalStore(subscribeToken, getToken, () => null);
  const [expired, setExpired] = useState(false);

  useEffect(
    () =>
      onUnauthorized(() => {
        setExpired(true);
        clearToken();
        queryClient.clear();
      }),
    [queryClient],
  );
  useEffect(() => {
    if (token) setExpired(false);
  }, [token]);

  const meQuery = useQuery({
    queryKey: ["me", token],
    queryFn: consoleApi.me,
    enabled: Boolean(token),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const signOut = useCallback(() => {
    clearToken();
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo<Session>(() => {
    const err = meQuery.error;
    let status: SessionStatus;
    if (!token) status = expired ? "expired" : "signed-out";
    else if (meQuery.isPending) status = "loading";
    else if (err instanceof ApiError && err.isUnauthenticated) status = "expired";
    else if (err instanceof ApiError && err.isForbidden) status = "forbidden";
    else if (err) status = "error";
    else if (meQuery.data && Object.keys(meQuery.data.permissions).length === 0)
      status = "no-access";
    else status = "authenticated";
    return {
      status,
      me: meQuery.data,
      error: err,
      can: (p, j) => canPermission(meQuery.data, p, j),
      signOut,
      retry: () => void meQuery.refetch(),
    };
  }, [token, expired, meQuery, signOut]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
