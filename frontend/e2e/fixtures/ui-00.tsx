import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ErrorState, LoadingState } from "../../src/shared/ui/AsyncState";
import { CoverageBar } from "../../src/shared/ui/CoverageBar";
import { Dialog } from "../../src/shared/ui/Dialog";
import { Disclosure } from "../../src/shared/ui/Disclosure";
import { EmptyState } from "../../src/shared/ui/EmptyState";
import { ProgressMeter } from "../../src/shared/ui/ProgressMeter";
import { StatusPill } from "../../src/shared/ui/StatusPill";
import { TabList, tabId, tabPanelId } from "../../src/shared/ui/Tabs";
import { bootstrapTheme } from "../../src/shared/platform/theme";
import "../../src/styles.css";
import "../../src/app/theme.css";
import "../../src/app/palette.generated.css";

type FixtureTab = "ready" | "unknown" | "blocked";

const FIXTURE_TABS = [
  { id: "ready", label: "Ready", detail: "Synthetic evidence" },
  { id: "unknown", label: "Unknown", detail: "Not reported" },
  { id: "blocked", label: "Unavailable", detail: "Capability closed" },
] as const;

bootstrapTheme();

function PrimitiveTour() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [tab, setTab] = useState<FixtureTab>("ready");

  return (
    <>
      <div data-testid="fixture-background">
        <main className="ui00-tour" id="main-content">
          <header className="ui00-tour__header">
            <p className="eyebrow">Synthetic browser fixture</p>
            <h1>UI-00 primitive state tour</h1>
            <p>
              Every value on this page is hardcoded fictional test evidence. The fixture performs no
              provider, session, health, authentication, or API request.
            </p>
          </header>

          <div className="ui00-tour__grid">
            <section aria-labelledby="ui00-loading-title" className="ui00-tour__card">
              <h2 id="ui00-loading-title">Loading</h2>
              <LoadingState label="Loading bounded synthetic evidence…" />
            </section>

            <section aria-labelledby="ui00-error-title" className="ui00-tour__card">
              <h2 id="ui00-error-title">Error</h2>
              <ErrorState
                actionLabel="Retry synthetic operation"
                message="The fictional operation failed safely without provider or session details."
                onRetry={() => setRetryCount((count) => count + 1)}
                title="Synthetic error state"
              />
              <output aria-live="polite">Synthetic retry requests: {retryCount}</output>
            </section>

            <section aria-labelledby="ui00-empty-title" className="ui00-tour__card">
              <h2 id="ui00-empty-title">Empty</h2>
              <EmptyState
                action={<button className="button button--secondary" type="button">Create synthetic item</button>}
                description="No observations exist in this bounded fictional fixture."
                title="No synthetic observations"
              />
            </section>

            <section aria-labelledby="ui00-closed-title" className="ui00-tour__card">
              <h2 id="ui00-closed-title">Closed</h2>
              <EmptyState
                description="This test capability is explicitly unavailable; no missing value is shown as zero."
                title="Synthetic capability unavailable"
                tone="closed"
              />
            </section>

            <section aria-labelledby="ui00-progress-title" className="ui00-tour__card">
              <h2 id="ui00-progress-title">Progress and coverage</h2>
              <ProgressMeter
                detail="Waiting for a fictional prerequisite"
                label="Unknown progress"
                state="idle"
                value={null}
              />
              <ProgressMeter
                detail="2 of 8 synthetic steps"
                label="Observed progress"
                max={8}
                state="active"
                value={2}
              />
              <CoverageBar coverage={0} eligible={0} observed={0} />
              <CoverageBar coverage={0.25} eligible={4} observed={1} />
            </section>

            <section aria-labelledby="ui00-status-title" className="ui00-tour__card">
              <h2 id="ui00-status-title">Status and disclosure</h2>
              <div aria-label="Synthetic status examples" className="ui00-tour__pills" role="group">
                <StatusPill tone="positive">Ready</StatusPill>
                <StatusPill tone="unknown">Unknown</StatusPill>
                <StatusPill tone="danger">Blocked</StatusPill>
              </div>
              <Disclosure detail="Always visible detail" summary="Synthetic provenance">
                <p>
                  Long fictional provenance wraps inside the disclosure without exposing a provider path,
                  transcript, account, repository, or machine identity.
                </p>
              </Disclosure>
            </section>

            <section aria-labelledby="ui00-tabs-title" className="ui00-tour__card ui00-tour__card--wide">
              <h2 id="ui00-tabs-title">Tabs</h2>
              <TabList
                idPrefix="ui00-fixture"
                label="Synthetic evidence states"
                onChange={setTab}
                tabs={FIXTURE_TABS}
                value={tab}
              />
              <div
                aria-labelledby={tabId("ui00-fixture", tab)}
                className="ui00-tour__tabpanel"
                id={tabPanelId("ui00-fixture", tab)}
                role="tabpanel"
              >
                Current synthetic state: {tab}
              </div>
            </section>

            <section aria-labelledby="ui00-dialog-title" className="ui00-tour__card ui00-tour__card--wide">
              <h2 id="ui00-dialog-title">Dialog</h2>
              <p>
                The deliberately tall fictional page verifies that opening a modal isolates and locks the
                background without moving the viewport.
              </p>
              <button
                className="button button--primary"
                onClick={() => setDialogOpen(true)}
                type="button"
              >
                Open synthetic dialog
              </button>
            </section>
          </div>

          <div aria-hidden="true" className="ui00-tour__scroll-space" />
        </main>
      </div>

      <Dialog
        description="This modal contains only hardcoded fictional browser-test content."
        footer={(
          <>
            <button className="button button--secondary" onClick={() => setDialogOpen(false)} type="button">
              Cancel
            </button>
            <button className="button button--primary" onClick={() => setDialogOpen(false)} type="button">
              Confirm synthetic action
            </button>
          </>
        )}
        onClose={() => setDialogOpen(false)}
        open={dialogOpen}
        title="Synthetic modal"
      >
        <p>
          A long but bounded modal paragraph exercises wrapping and scrolling at a 360 pixel viewport.
          Nothing here was read from a provider or local session.
        </p>
        <label>
          Fictional choice
          <select defaultValue="unknown">
            <option value="unknown">Unknown</option>
            <option value="ready">Ready</option>
          </select>
        </label>
      </Dialog>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<PrimitiveTour />);
