# Converge-04 handoff — packaged Agent core-loop evidence

Status: automated acceptance instrumentation complete on 2026-09-04; packaged
owner and physical-model execution pending; checkpoint not release-complete

## Outcome

Converge-04 can no longer report success from a partial model chat. The native
owner-check surface now keeps one content-free, page-local evidence receipt and
requires the complete Agent core loop before it shows `Complete`:

- a local-history chat recovered after an application restart;
- a clean stopped runtime baseline and an admitted workspace root;
- capability-verified startup of the first selected model;
- one completed streamed response and one explicitly stopped response;
- one approved, verified workspace write and one approved command;
- the live Files & review contract and a successfully revalidated artifact
  viewer;
- truthful known-or-unknown context evidence after a completed turn;
- a different second model becoming ready; and
- final unload, owned-process exit, and measured GPU cleanup (or an explicit
  CPU-only `not_required` receipt) for the latest ready runtime.

The earlier check could show `Complete` after only a chat, Stop, review request
and unload. It also stored its receipt inside the Settings tab, so closing
Settings erased the run while the owner used the normal Agent controls. Both
defects are repaired. The receipt is now owned by the Agent page, survives
closing and reopening Settings, remains memory-only, and clears on reload.

Artifact evidence advances only after the selected version is revalidated and a
supported text, document, image or PDF view is actually ready. A stale revision,
failed safe-document projection, media mismatch or decode failure does not count
as a successful view.

The opt-in physical GGUF workflow probe is now
`local-model-workflow-probe.v2`. It unloads through the shared coordinator rather
than treating a raw service shutdown as lifecycle proof. Its success result now
requires no visible runtime window, an idle coordinator, confirmed process exit,
and measured GPU cleanup (or an explicit CPU-only not-required state). The probe
still uses only a disposable reserved-example workspace and prints content-free
booleans/state codes.

## Current automated evidence

- Focused acceptance and artifact components: **44/44 passed**.
- Full Agent page component suite: **166/166 passed**.
- Artifact viewer success/refusal rerun after the negative assertions:
  **35/35 passed**.
- Agent/workspace/artifact responsive browser journeys at 360 and 1440 px:
  **89/89 passed** with one worker.
- Intercepted frontend/HTTP contract matrix: **41/41 passed** with one worker.
- Production-built, zero-interception real-loopback matrix: **16/16 passed**.
- Desktop lifecycle, native-window, folder-picker, local-model, command,
  artifact and process-ownership backend group: **145/145 passed**.
- Production frontend TypeScript build: passed.
- Physical-probe compile and CLI smoke: passed.

The zero-interception shutdown receipt reported the listener released, runtime
cleanup confirmed, server thread clean, temporary state removed and **0 model
runtimes remaining**. That is strong disposable-stack evidence, not a claim
about physical VRAM or the installed desktop package.

## Refusal and truth cases retained

- The owner check cannot start without native user-presence confirmation.
- It never starts/stops a model, sends a prompt, opens a workspace, writes a
  file or runs a command on the owner's behalf.
- A partial lifecycle cannot show `Complete`.
- Evidence cannot be combined across chats.
- Unknown or failed cleanup remains red and blocks completion.
- A second ready revision for the same alias is not a model switch.
- Loading the second model clears any earlier unload/cleanup proof; the latest
  runtime must be stopped cleanly.
- Stale, missing, malformed or failed artifact previews do not create viewer
  evidence.
- Production web fetch remains excluded: the UI does not advertise permission
  when no governed fetcher is composed, and session creation rejects it.

## Still owner-gated and unproven

Converge-04 is not closed until the following are observed in the packaged
native application:

- native Windows folder selection and native approval dialogs;
- retained-chat recovery across a real application restart;
- physical CPU, GPU and supported split placement as applicable to the selected
  models and hardware;
- two admitted compatible model aliases starting/switching correctly;
- long-running generation Stop behavior;
- approved write and command effects with objective read-back;
- a generated/reviewed artifact opened in its real viewer;
- final process-tree exit and physical accelerator-memory evidence;
- exactly one application listener and no visible or orphan terminal/process
  tree during launch, model work, switch, unload and shutdown; and
- packaged close/reopen cleanup.

Installer/update apply, relaunch and rollback are Converge-07 and are not folded
into this checkpoint.

## Owner click-later checklist

Save or send any current draft before beginning; this implementation did not
reload the owner's open application.

1. In the packaged native app, create a retained (`local history`) Agent chat,
   close the app cleanly, reopen it and resume that exact chat.
2. Confirm only one Prompt Enhancer window/listener appears and no terminal
   window flashes.
3. Open `Agent settings` → `Owner checks` and choose
   `Begin guarded acceptance`. Close Settings; the receipt must remain active.
4. Choose a disposable test workspace with the native `Browse` control, open
   `Files & review`, and return to the conversation.
5. Load compatible model A. Complete one small response, then start a separate
   long response and use `Stop`.
6. In the disposable workspace, approve one reviewed file write and one bounded
   command. Confirm their terminal receipts and objective file/test result.
7. Open the recorded artifact in its viewer. A failed or stale preview must not
   count.
8. Switch to compatible model B and wait for its exact ready identity. Stop the
   shared model after it becomes ready.
9. Return to `Owner checks` and choose `Check current evidence`. `Complete` is
   valid only when every row passes and cleanup is measured or explicitly
   CPU-only.
10. Close and reopen the package once more, confirming no orphan process,
    terminal window or unexpected listener remains.

The acceptance receipt stores no path, prompt, command output or artifact bytes.
Do not paste private workspace or conversation content into the checkpoint
record.

## Next boundary

The next dependency action for Converge-04 is the owner-run package/hardware
check above. Safe repository work in Converge-05 can be prepared independently,
but this checkpoint must remain visibly pending until the native evidence is
recorded.
