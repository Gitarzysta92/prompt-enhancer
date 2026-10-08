# Checkpoint Agent-12e entry: model-neutral chat entry

Date: 2026-09-01

This checkpoint makes the integrated Agent composer reachable without loading,
selecting, or inheriting a local model during New session setup. Tests use only
synthetic projects, chats, folders, models, and runtime receipts.

## Frozen owner-visible contract

1. A workspace and a model are independent choices. An existing absolute
   workspace can open as a project chat while no model is installed, running,
   or bound.
2. New session defaults to **choose the model in chat**. A running shared model
   is never silently inherited, started, or pinned to the new chat.
3. The open chat displays the integrated Model & context control beside the
   message composer. Sending stays disabled until the person explicitly
   chooses/starts a model and the exact chat is bound to it.
4. An explicitly selected optional setup model may retain the existing
   start-and-bind path, but it is not the default and its readiness cannot block
   a model-neutral chat.
5. Choosing a model in one active chat cannot preselect that model in a later
   New session.
6. In the protected native Agent window, Browse remains the narrow native
   folder dialog. In an ordinary localhost browser, the UI presents editable
   absolute-path entry instead of a disabled control that looks model-gated.
   No browser surface claims access to a Windows folder chooser that it does
   not have.
7. Creating a model-neutral chat loads no model and consumes no model VRAM.

## Required evidence

1. Frontend tests prove a chat opens with `model_alias: null` when no model is
   running, while the model catalogue is still loading, and while another
   shared model is already running.
2. A regression test proves an active-chat runtime selection does not leak into
   the next New session.
3. Browser and native folder-entry tests prove the manual field remains enabled,
   the browser state is truthful, and the real native bridge still provides
   Browse, cancel, and exact selected-path behavior.
4. Focused Agent tests, full frontend tests, production build, relevant backend
   session/API/privacy tests, and live localhost DOM verification pass with no
   model process started.
