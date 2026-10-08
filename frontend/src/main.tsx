import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { BootstrapFailure, BootstrapLoading } from "./app/BootstrapState";
import { createHttpTransport } from "./shared/api/httpTransport";
import {
  createTeamControlPlanePortForRuntime,
  teamControlPlanePortForOverlay,
} from "./shared/api/teamControlPlaneRuntime";
import { createSocialHubPortForRuntime } from "./shared/api/socialHubRuntime";
import { createBrowserPlatform } from "./shared/platform/browserPlatform";
import {
  createRuntimeComposition,
  resolveRuntimeDataMode,
} from "./shared/platform/runtimeMode";
import { startUiRevisionGuard } from "./shared/platform/uiRevisionGuard";
import "./styles.css";
import "./app/theme.css";
import "./app/palette.generated.css";
import { bootstrapTheme } from "./shared/platform/theme";

bootstrapTheme();

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("The application root is unavailable.");
}
const root = createRoot(rootElement);
root.render(
  <StrictMode>
    <BootstrapLoading />
  </StrictMode>,
);

async function mountApp() {
  const mode = resolveRuntimeDataMode({
    development: import.meta.env.DEV,
    viteMode: import.meta.env.MODE,
  });
  const syntheticPreview = mode === "synthetic_demo";
  const transport = syntheticPreview
    ? (await import("./shared/api/syntheticTransport")).createSyntheticTransport()
    : createHttpTransport();
  const runtime = createRuntimeComposition(mode, transport);
  const uiRevisionGuard = startUiRevisionGuard({
    enabled: !syntheticPreview,
    moduleUrl: import.meta.url,
  });

  if (import.meta.hot) {
    import.meta.hot.dispose(() => uiRevisionGuard.dispose());
  }

  const teamControlPlane = createTeamControlPlanePortForRuntime(
    mode,
    mode === "local_real" ? runtime.transport : undefined,
  );
  const socialHub = createSocialHubPortForRuntime(mode);
  const overlay = /^\/overlay\/model-ensemble\/?$/.test(window.location.pathname);
  const Root = overlay
    ? (await import("./features/model-ensemble")).ModelEnsembleOverlay
    : null;
  root.render(
    <StrictMode>
      {Root === null
        ? <App platform={createBrowserPlatform()} runtime={runtime} socialHub={socialHub} teamControlPlane={teamControlPlane} />
        : <Root
          teamControlPlane={teamControlPlanePortForOverlay(mode, teamControlPlane)}
          transport={runtime.transport}
        />}
    </StrictMode>,
  );
}

void mountApp().catch(() => {
  root.render(
    <StrictMode>
      <BootstrapFailure onRetry={() => window.location.reload()} />
    </StrictMode>,
  );
});
