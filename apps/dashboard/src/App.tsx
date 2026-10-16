import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { Navigate, Outlet, RouterProvider, createBrowserRouter } from "react-router";

import { AlertsLogPage } from "./features/admin/AlertsLogPage";
import { TagsPage } from "./features/admin/TagsPage";
import { LoginPage } from "./features/auth/LoginPage";
import { ConsolePage } from "./features/console/ConsolePage";
import { TopBar } from "./features/console/TopBar";
import { useLiveConnection, useSession, useSite, type SiteGeo } from "./lib/hooks";
import { useLive } from "./state/live";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function Shell({ site }: { site: SiteGeo }) {
  useLiveConnection(site.id);
  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <TopBar siteName={site.name} timezone={site.timezone} />
      <Outlet />
    </div>
  );
}

function makeRouter(site: SiteGeo) {
  return createBrowserRouter([
    {
      element: <Shell site={site} />,
      children: [
        { path: "/", element: <ConsolePage site={site} /> },
        { path: "/alerts", element: <AlertsLogPage siteId={site.id} /> },
        { path: "/tags", element: <TagsPage siteId={site.id} /> },
        { path: "*", element: <Navigate to="/" replace /> },
      ],
    },
  ]);
}

function Authenticated() {
  const site = useSite();
  const reset = useLive((s) => s.reset);
  useEffect(() => reset, [reset]);
  const router = useMemo(() => (site.data ? makeRouter(site.data) : null), [site.data]);
  if (site.isError) {
    return (
      <div className="grid h-full place-items-center text-sm text-critical">
        {site.error.message}
      </div>
    );
  }
  if (!router) {
    return (
      <div className="hud-title grid h-full animate-pulse place-items-center">Acquiring site…</div>
    );
  }
  return <RouterProvider router={router} />;
}

export function App() {
  const session = useSession();
  return (
    <QueryClientProvider client={queryClient}>
      {session ? <Authenticated key={session.user.id} /> : <LoginPage />}
    </QueryClientProvider>
  );
}
