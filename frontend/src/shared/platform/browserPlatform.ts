import type { AppRoute, PlatformAdapter } from "./platform";
import { parseRoute, routePath } from "./platform";

/** Browser-only navigation. A future desktop host implements PlatformAdapter. */
export function createBrowserPlatform(browserWindow: Window = window): PlatformAdapter {
  const listeners = new Set<(route: AppRoute) => void>();
  let popstateAttached = false;
  const comparablePath = (path: string) =>
    path !== "/" && path.endsWith("/") && !path.endsWith("//") ? path.slice(0, -1) : path;
  const emit = () => {
    const route = parseRoute(browserWindow.location.pathname);
    listeners.forEach((listener) => listener(route));
  };

  const attachPopstate = () => {
    if (popstateAttached) return;
    browserWindow.addEventListener("popstate", emit);
    popstateAttached = true;
  };
  const detachPopstate = () => {
    if (!popstateAttached || listeners.size > 0) return;
    browserWindow.removeEventListener("popstate", emit);
    popstateAttached = false;
  };

  return {
    currentRoute: () => parseRoute(browserWindow.location.pathname),
    navigate(route) {
      const nextPath = routePath(route);
      if (comparablePath(browserWindow.location.pathname) === comparablePath(nextPath)) return;
      browserWindow.history.pushState(null, "", nextPath);
      emit();
    },
    subscribe(listener) {
      listeners.add(listener);
      attachPopstate();
      return () => {
        listeners.delete(listener);
        detachPopstate();
      };
    },
  };
}
