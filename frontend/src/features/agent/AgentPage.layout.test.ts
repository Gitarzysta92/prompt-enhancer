import { describe, expect, it } from "vitest";
import appCss from "../../styles.css?raw";
import controllerCss from "./AgentControllerPanel.css?raw";
import mcpConnectionsCss from "./AgentMcpConnectionsPanel.css?raw";
import agentPageCss from "./AgentPage.css?raw";
import catalogRailCss from "./AgentCatalogRail.css?raw";
import discoveryCss from "./AgentWorkspaceDiscoveryPanel.css?raw";
import acceptanceCss from "./AgentNativeAcceptancePanel.css?raw";
import runtimeControlCss from "./AgentRuntimeControl.css?raw";
import reviewDrawerCss from "./AgentReviewDrawer.css?raw";
import readinessCss from "./AgentReadinessPanel.css?raw";
import artifactsCss from "./AgentArtifactsPanel.css?raw";
import attachmentsCss from "./AgentComposerAttachments.css?raw";
import diffViewerCss from "./AgentDiffViewer.css?raw";
import mcpStoreCss from "./AgentMcpStorePanel.css?raw";
import mcpProjectToolsCss from "./AgentMcpProjectToolsPanel.css?raw";
import teamFoldersCss from "./TeamFoldersPanel.css?raw";
import copyButtonCss from "./AgentCopyButton.css?raw";
import changeSetCss from "./AgentChangeSetPanel.css?raw";
import artifactCaptureCss from "./AgentArtifactCaptureDialog.css?raw";
import documentPreviewCss from "./AgentDocumentPreview.css?raw";
import mcpToolActivityCss from "./AgentMcpToolActivity.css?raw";
import messageContentCss from "./AgentMessageContent.css?raw";
import sessionEffectsCss from "./AgentSessionEffects.css?raw";
import pdfPreviewCss from "./AgentPdfPreview.css?raw";

describe("AgentPage layout contract", () => {
  it("uses one legible caption floor and shared touch target in the core Agent workspace", () => {
    expect(appCss).toMatch(/--type-caption:\s*0\.75rem;/);
    expect(appCss).toMatch(/--touch-target:\s*2\.75rem;/);

    for (const css of [agentPageCss, catalogRailCss, runtimeControlCss, readinessCss]) {
      const hardCodedRemSizes = [...css.matchAll(/font-size:\s*(0?\.\d+)rem/g)].map((match) => Number(match[1]));
      expect(hardCodedRemSizes.filter((size) => size < 0.75)).toEqual([]);
    }

    expect(agentPageCss).toMatch(/\.agent__settings-tabs button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(agentPageCss).toMatch(/\.agent \.button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(catalogRailCss).toMatch(/\.agent-rail__menu-trigger\s*\{[^}]*width:\s*var\(--touch-target\);[^}]*min-height:\s*var\(--touch-target\);/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__actions \.button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
  });

  it("extends the legibility floor and touch target across Agent secondary surfaces", () => {
    const secondaryCss = [
      controllerCss,
      mcpConnectionsCss,
      mcpStoreCss,
      teamFoldersCss,
      artifactsCss,
      attachmentsCss,
      reviewDrawerCss,
      discoveryCss,
      diffViewerCss,
      copyButtonCss,
      changeSetCss,
      artifactCaptureCss,
      documentPreviewCss,
      mcpProjectToolsCss,
      mcpToolActivityCss,
      messageContentCss,
      sessionEffectsCss,
      pdfPreviewCss,
    ];

    for (const css of secondaryCss) {
      const remSizes = [...css.matchAll(/font-size:\s*(0?\.\d+)rem/g)].map((match) => Number(match[1]));
      const pixelSizes = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)].map((match) => Number(match[1]));
      const shorthandRemSizes = [...css.matchAll(/font:\s*[^;\n]*?(0?\.\d+)rem\//g)].map((match) => Number(match[1]));
      expect(remSizes.filter((size) => size < 0.75)).toEqual([]);
      expect(pixelSizes.filter((size) => size < 12)).toEqual([]);
      expect(shorthandRemSizes.filter((size) => size < 0.75)).toEqual([]);
    }

    expect(teamFoldersCss).toMatch(/\.team-folders__form input\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(mcpConnectionsCss).toMatch(/\.agent-mcp-connections__client-tabs \.button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__tabs button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__filters span\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-managed__runtime-preview summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(reviewDrawerCss).toMatch(/\.agent-review__tabs button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(attachmentsCss).toMatch(/\.agent-attachments__document-preview summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(copyButtonCss).toMatch(/\.agent-copy-button\s*\{[^}]*min-width:\s*var\(--touch-target\);[^}]*min-height:\s*var\(--touch-target\);/);
    expect(mcpToolActivityCss).toMatch(/\.agent-mcp-call__details > summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(sessionEffectsCss).toMatch(/\.agent-session-effects > summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(documentPreviewCss).toMatch(/\.agent-document-preview__section-button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(pdfPreviewCss).toMatch(/\.agent-pdf-preview__toolbar \[role="group"\] \.button\s*\{[^}]*min-width:\s*var\(--touch-target\);[^}]*min-height:\s*var\(--touch-target\);/);
  });

  it("removes the redundant global rail while preserving compact navigation at medium widths", () => {
    expect(appCss).toMatch(/@media \(min-width:\s*861px\) and \(max-width:\s*1180px\)[\s\S]*?\.app-shell--agent-focus\s*\{[^}]*display:\s*block;/);
    expect(appCss).toMatch(/\.app-shell--agent-focus > \.sidebar,[\s\S]*?\.app-shell--agent-focus > \.workspace > \.topbar\s*\{\s*display:\s*none;/);
    expect(appCss).toMatch(/\.app-shell--agent-focus > \.mobile-shell-header\s*\{[^}]*display:\s*grid;[^}]*grid-template-areas:\s*"identity runtime actions";/);
    expect(appCss).toMatch(/\.app-shell--agent-focus \.mobile-shell-header__menu\s*\{[^}]*display:\s*inline-flex;/);
  });

  it("does not let tall neighboring panels stretch the conversation below the viewport", () => {
    expect(agentPageCss).toMatch(/\.agent__layout\s*\{[^}]*align-items:\s*start;/);
    expect(agentPageCss).toMatch(/\.agent__workbench\s*\{[^}]*align-items:\s*start;[^}]*align-self:\s*start;/);
    expect(agentPageCss).toMatch(/\.agent__main\s*\{[^}]*height:\s*clamp\(28rem,\s*calc\(100dvh\s*-\s*15rem\),\s*46rem\);/);
  });

  it("keeps the transcript as the shrinking scroll region and preserves full-height window mode", () => {
    expect(agentPageCss).toMatch(/\.agent__log\s*\{[^}]*overflow-y:\s*auto;[^}]*min-height:\s*0;/);
    expect(agentPageCss).toMatch(/\.agent__layout--window \.agent__main\s*\{\s*height:\s*100%;\s*}/);
    expect(agentPageCss).toMatch(/\.agent\[data-active-session="true"\]:not\(\.agent--window\) \.agent__main,[\s\S]*?height:\s*clamp\(28rem,\s*calc\(100dvh\s*-\s*9\.5rem\),\s*50rem\);/);
  });

  it("keeps the conversation in place and promotes review to an overlay sheet below 1380 px", () => {
    expect(agentPageCss).toMatch(/@media \(max-width:\s*1380px\)[\s\S]*?\.agent__workbench\[data-has-workspace="true"\] > \.agent__main\s*\{\s*grid-row:\s*1;/);
    expect(agentPageCss).toMatch(/@media \(max-width:\s*1380px\)[\s\S]*?\.agent__workbench\[data-has-workspace="true"\] > \.agent-review\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*72;/);
    expect(agentPageCss).toMatch(/@media \(max-width:\s*1380px\)[\s\S]*?\.agent__review-backdrop\s*\{[^}]*position:\s*fixed;[^}]*display:\s*block;/);
  });

  it("keeps the activity overview, timeline, and responsive chat hierarchy explicit", () => {
    expect(agentPageCss).toMatch(/\.agent__activity-overview\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:/);
    expect(agentPageCss).toMatch(/\.agent__timeline::before\s*\{[^}]*background:\s*var\(--line-strong\);[^}]*content:\s*"";/);
    expect(agentPageCss).toMatch(/@media \(max-width:\s*900px\)[\s\S]*?\.agent__activity-overview\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  });

  it("keeps project navigation in the rail and model context in the active composer", () => {
    expect(agentPageCss).toMatch(/\.agent__side\s*\{[^}]*grid-template-rows:\s*minmax\(12rem,\s*1fr\) auto;[^}]*min-width:\s*0;[^}]*height:\s*clamp\(32rem,\s*calc\(100dvh\s*-\s*15rem\),\s*46rem\);[^}]*overflow:\s*hidden;/);
    expect(agentPageCss).toMatch(/\.agent__side-scroll\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/);
    expect(agentPageCss).toMatch(/\.agent__settings-launch\s*\{[^}]*min-width:\s*0;/);
    expect(agentPageCss).toMatch(/\.agent__compose-footer\s*\{[^}]*grid-template-columns:\s*minmax\(14rem,\s*1fr\) auto;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime--composer\s*\{[^}]*width:\s*min\(100%,\s*44rem\);[^}]*max-height:\s*none;[^}]*overflow:\s*visible;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__composer-disclosure > summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__composer-disclosure\s*\{[^}]*position:\s*relative;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__composer-panel\s*\{[^}]*position:\s*absolute;[^}]*bottom:\s*calc\(100% \+ 0\.5rem\);[^}]*max-height:\s*min\([^;]*dvh[^;]*\);[^}]*overflow-y:\s*auto;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__composer-panel-head\s*\{[^}]*position:\s*sticky;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__composer-actions\s*\{[^}]*position:\s*sticky;/);
    expect(agentPageCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent__compose-primary-action \.agent__forced-color-label\s*\{[^}]*position:\s*static;[^}]*clip:\s*auto;/);
    expect(attachmentsCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-attachments--compact \.agent-attachments__forced-color-label\s*\{[^}]*position:\s*static;[^}]*clip:\s*auto;/);
  });

  it("releases the fixed-height rail and stacks runtime controls on narrow screens", () => {
    expect(agentPageCss).toMatch(/@media \(max-width:\s*900px\)[\s\S]*?\.agent__side\s*\{[^}]*height:\s*auto;[^}]*overflow:\s*visible;/);
    expect(runtimeControlCss).toMatch(/@media \(max-width:\s*900px\)[\s\S]*?\.agent-runtime\s*\{[^}]*max-height:\s*none;[^}]*overflow:\s*visible;/);
    expect(runtimeControlCss).toMatch(/@media \(max-width:\s*480px\)[\s\S]*?\.agent-runtime__placement, \.agent-runtime__facts\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\);\s*}/);
    expect(runtimeControlCss).toMatch(/@media \(max-width:\s*480px\)[\s\S]*?\.agent-runtime__actions\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\) auto;\s*}/);
  });

  it("keeps drawer controls touch-sized and fits health facts to the card rather than the viewport", () => {
    expect(agentPageCss).toMatch(/\.agent__drawer-head \.button\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(agentPageCss).toMatch(/\.agent__settings-tabs button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(agentPageCss).toMatch(/\.button\.agent__settings-trigger\s*\{[^}]*min-height:\s*3\.35rem;/);
    expect(agentPageCss).toMatch(/\.agent__run-actions \.button, \.agent__model-actions \.button\s*\{\s*min-height:\s*2\.75rem;/);
    expect(reviewDrawerCss).toMatch(/\.agent-review__head > \.button\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(reviewDrawerCss).toMatch(/\.agent-review__tabs button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(controllerCss).toMatch(/\.agent-controller__advanced > summary\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(controllerCss).toMatch(/\.agent-controller__health-facts\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit,/);
    expect(controllerCss).toMatch(/\.agent-controller__health > \.button\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(acceptanceCss).toMatch(/\.agent-acceptance > \.button,[\s\S]*?min-height:\s*2\.75rem;/);
    expect(catalogRailCss).toMatch(/\.agent-rail__icon-button\s*\{[^}]*width:\s*2\.75rem;[^}]*height:\s*2\.75rem;/);
    expect(catalogRailCss).toMatch(/\.agent-rail__search input\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(catalogRailCss).toMatch(/\.agent-rail__project-pick,[\s\S]*?min-height:\s*3rem;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime select\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__details > summary\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(runtimeControlCss).toMatch(/\.agent-runtime__actions \.button\s*\{[^}]*min-height:\s*var\(--touch-target\);/);
    expect(agentPageCss).toMatch(/\.agent__reasoning summary\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(agentPageCss).toMatch(/\.agent__result summary\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(agentPageCss).toMatch(/\.agent__jump-latest\s*\{[^}]*position:\s*sticky;[^}]*min-height:\s*2\.75rem;/);
    expect(agentPageCss).toMatch(/\.agent-workspace__support > summary\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(agentPageCss).toMatch(/\.agent-workspace__transaction-diffs summary\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(discoveryCss).toMatch(/\.agent-discovery__search input\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(discoveryCss).toMatch(/\.agent-discovery__content-search form input\[type="search"\],[\s\S]*?min-height:\s*2\.75rem;/);
    expect(discoveryCss).not.toMatch(/\.agent-discovery__regex\s*\{[^}]*min-height:\s*auto;/);
    expect(attachmentsCss).toMatch(/\.agent-attachments__toolbar \.button,[\s\S]*?min-height:\s*2\.75rem;/);
    expect(attachmentsCss).toMatch(/\.agent-attachments__picker-actions \.button,[\s\S]*?min-height:\s*2\.75rem;/);
    expect(attachmentsCss).toMatch(/\.agent-attachments__list \.button\s*\{[\s\S]*?min-height:\s*2\.75rem;/);
    expect(artifactsCss).toMatch(/\.agent-artifacts \.button\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(artifactsCss).toMatch(/\.agent-artifacts__version-select select\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(artifactsCss).toMatch(/\.agent-artifacts__comparison-controls select\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(artifactsCss).toMatch(/\.agent-artifacts__media-toolbar \[role="group"\] \.button\s*\{[^}]*min-width:\s*44px;[^}]*min-height:\s*2\.75rem;/);
  });

  it("gives MCP management a wide progressive workspace without turning the chat into a settings page", () => {
    expect(agentPageCss).toMatch(/\.agent__settings-drawer\[data-settings-tab="store"\]\s*\{[^}]*width:\s*min\(76rem,\s*calc\(100vw\s*-\s*4rem\)\);/);
    expect(agentPageCss).toMatch(/\.agent__settings-tabs\s*\{[^}]*grid-template-columns:\s*repeat\(5,\s*minmax\(0,\s*1fr\)\);/);
    expect(agentPageCss).toMatch(/@media \(max-width:\s*620px\)[\s\S]*?\.agent__settings-tabs\s*\{[^}]*display:\s*flex;[^}]*overflow-x:\s*auto;/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__tabs\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__toolbar\s*\{[^}]*grid-template-columns:\s*minmax\(15rem,\s*1fr\) auto minmax\(9rem,\s*0\.42fr\);/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__sort select\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(mcpStoreCss).toMatch(/\.agent-mcp-store__grid\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit,/);
    expect(mcpStoreCss).toMatch(/@media \(max-width:\s*820px\)[\s\S]*?\.agent-mcp-store__search\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/);
    expect(mcpStoreCss).toMatch(/@media \(max-width:\s*520px\)[\s\S]*?\.agent-mcp-store__toolbar\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/);
    expect(mcpStoreCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-mcp-store__boundary,[\s\S]*?\.agent-mcp-store__tabs,[\s\S]*?border-color:\s*CanvasText;/);
    expect(mcpProjectToolsCss).toMatch(/\.agent-mcp-project-tools > summary\s*\{[^}]*min-height:\s*2\.9rem;/);
    expect(mcpProjectToolsCss).toMatch(/@media \(max-width:\s*520px\)[\s\S]*?\.agent-mcp-project-tools dl\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
    expect(mcpProjectToolsCss).toMatch(/@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?transition:\s*none;/);
    expect(mcpProjectToolsCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-mcp-project-tools,[\s\S]*?border-color:\s*CanvasText;/);
  });

  it("renders project and chat actions in a viewport-bounded sheet outside rail scrollers", () => {
    expect(catalogRailCss).toMatch(/\.agent-rail__action-backdrop\s*\{[^}]*position:\s*fixed;[^}]*inset:\s*0;/);
    expect(catalogRailCss).toMatch(/\.agent-rail__action-dialog\s*\{[^}]*max-height:\s*min\(80dvh,\s*36rem\);[^}]*overflow:\s*auto;/);
    expect(catalogRailCss).toMatch(/\.agent-rail__action-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/);
    expect(catalogRailCss).toMatch(/\.agent-rail__action-grid > button\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(catalogRailCss).not.toMatch(/\.agent-rail__action-dialog\s*\{[^}]*position:\s*absolute;/);
  });

  it("keeps readiness evidence readable at phone width and in forced colors", () => {
    expect(readinessCss).toMatch(/@media \(max-width:\s*380px\)[\s\S]*?\.agent-readiness__facts,[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
    expect(readinessCss).toMatch(/@media \(max-width:\s*620px\)[\s\S]*?\.agent-readiness__capabilities li\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/);
    expect(readinessCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-readiness__capabilities li,[\s\S]*?border-color:\s*CanvasText;/);
    expect(agentPageCss).toMatch(/@media \(max-width:\s*900px\)[\s\S]*?\.agent__settings-tabs\s*\{\s*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/);
  });

  it("keeps rich diff review bounded, touch-sized, responsive, and forced-color visible", () => {
    expect(diffViewerCss).toMatch(/\.agent-diff-viewer__viewport\s*\{[^}]*max-height:\s*22rem;[^}]*overflow:\s*auto;/);
    expect(diffViewerCss).toMatch(/\.agent-diff-viewer__toggle\s*\{[^}]*min-height:\s*2\.75rem;/);
    expect(diffViewerCss).toMatch(/\.agent-diff-viewer__actions \.agent-copy-button\s*\{\s*min-height:\s*2\.75rem;/);
    expect(diffViewerCss).toMatch(/@media \(max-width:\s*680px\)[\s\S]*?\.agent-diff-viewer__toolbar\s*\{[^}]*flex-direction:\s*column;/);
    expect(diffViewerCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-diff-viewer tbody tr\s*\{[^}]*border-color:\s*CanvasText;/);
  });

  it("keeps artifact lineage comparison readable on phones and in forced colors", () => {
    expect(artifactsCss).toMatch(/@media \(max-width:\s*700px\)[\s\S]*?\.agent-artifacts__comparison dl\s*\{\s*grid-template-columns:\s*1fr;/);
    expect(artifactsCss).toMatch(/@media \(max-width:\s*520px\)[\s\S]*?\.agent-artifacts__card\s*\{[^}]*grid-template-columns:\s*auto minmax\(0,\s*1fr\);/);
    expect(artifactsCss).toMatch(/@media \(max-width:\s*520px\)[\s\S]*?\.agent-artifacts__card-actions\s*\{[^}]*grid-column:\s*1 \/ -1;/);
    expect(artifactsCss).toMatch(/@media \(forced-colors:\s*active\)[\s\S]*?\.agent-artifacts__comparison\s*\{\s*border-color:\s*CanvasText;/);
  });
});
