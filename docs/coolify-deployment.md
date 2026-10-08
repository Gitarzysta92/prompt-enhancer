# Private browser deployment with Coolify

The publishing workflow deploys to a configured Coolify application. Set the
non-secret destination URLs in GitHub repository variables; store credentials
in GitHub/Coolify secret storage. This deployment requires Cloudflare Access on
both the controller and the application, including its health endpoint. Use
existing Service Auth tokens where their policies authorize these destinations.

The optional hosted profile serves one owner's workspace behind HTTPS and a
password. Everyone with that password shares the same data and authority. It is
not a public multi-user service. Normal CLI/desktop operation remains loopback-only.

The infrastructure repository manages the VM underlay. Application deployment
belongs to the existing Coolify controller; choose the intended managed server
as this application's destination. Do not install another controller on it.
Infrastructure addresses, identities and tokens belong in private configuration.

## Configure the application once

1. In the controller, create a **Docker Image** application on the intended
   managed server. Use `ghcr.io/<repository-owner>/<repository-name>` (lowercase),
   tag `production`. Leave the digest empty. The first deployment must wait until
   the workflow has published the image.
2. Set **Ports Exposes** to `8080`, configure the intended HTTPS domain and its
   DNS, and let the Coolify proxy terminate TLS. Leave **Ports Mappings** empty.
   Only the proxy should reach port 8080; it must replace `X-Forwarded-Proto`
   with the actual public request scheme. Do not expose backend port 8765.
3. Add the runtime variables below. Store them in Coolify, not in a committed
   environment file. Password hashes must retain their literal dollar signs;
   use Coolify's literal/raw variable setting where available.
4. Mount an application-owned persistent volume at `/data`, writable by UID/GID
   `10001:10001`. New named volumes inherit the image directory ownership; a
   pre-existing mount needs that ownership set by its administrator. Use one
   replica and enable **Consistent Container Name** in the application's advanced
   settings. This makes Coolify stop the old container before starting its
   replacement, preventing overlapping processes on the shared SQLite volume.
5. Use `GET /health` on port 8080 for health checks. The image also defines its own
   Docker health check. Leave the image entrypoint/start command unchanged.
6. If the GHCR package is private, configure registry pull authentication on the
   deployment server as the user Coolify uses. Do not make the package public as
   a workaround. Do not mount provider homes, personal repositories or the Docker
   socket into the application.

| Runtime variable | Value |
| --- | --- |
| `PROMPT_ENHANCER_PUBLIC_HOST` | DNS name only, such as `prompt.example.test`; no scheme, path or port |
| `PROMPT_ENHANCER_WEB_USER` | A dedicated login name using letters, digits, `_` or `-` |
| `PROMPT_ENHANCER_WEB_PASSWORD_HASH` | Bcrypt hash from interactive `caddy hash-password` (cost 10–16); never a plaintext password |

Do not override `PROMPT_ENHANCER_REVISION`; the workflow bakes it into the image.
The container refuses to start with missing or malformed gateway settings.

## Configure GitHub Actions

Create the `production` environment and restrict its deployment branches to
`main`. Configure required reviewers if your GitHub plan supports them. The
workflow's branch check complements repository review rules; it does not replace
branch protection. Publishing requires the repository to permit `GITHUB_TOKEN`
package writes, and an existing GHCR package must grant this repository access.

Set these environment secrets:

| Secret | Purpose |
| --- | --- |
| `COOLIFY_TOKEN` | Dedicated, expiring Coolify API token with only `deploy` permission in the appropriate team |
| `COOLIFY_ACCESS_CLIENT_ID` | Client ID of a Cloudflare Access service token permitted by the controller application's Service Auth policy |
| `COOLIFY_ACCESS_CLIENT_SECRET` | Corresponding Cloudflare Access service-token secret |
| `PROMPT_ENHANCER_ACCESS_CLIENT_ID` | Client ID of an existing Access service token authorized for the application's health endpoint |
| `PROMPT_ENHANCER_ACCESS_CLIENT_SECRET` | Corresponding application Access service-token secret |

Set the repository variables `COOLIFY_WEBHOOK` to the HTTPS deployment URL for
one Coolify application and `COOLIFY_PUBLIC_URL` to the application HTTPS URL.
Keep these infrastructure addresses out of the public source.
The controller credential pair is sent only to
the controller; the application pair is sent only to `/health`. The Coolify API
token never reaches the application. An existing service token authorized for
both destinations can supply both pairs; a new token is not required merely to
use this workflow. Missing application credentials or an incomplete pair fail
before a deployment is triggered. Controller Access credentials may be omitted
when using an authenticated private SSH tunnel to the controller.

Keep the human login policies on both Cloudflare Access applications. Add or
reuse **Service Auth** policies with an **Include → Service Token** rule for the
existing CI token. Requests must still authenticate as an allowed person or
service. Keep `/health` protected at Cloudflare; do not add a Bypass policy or
an Everyone rule. The container's internal health check needs no Cloudflare
credential because it stays on loopback. Keep the origin reachable only through
the tunnel or trusted private network so direct Internet traffic cannot avoid
Access. Cloudflare policy and origin restrictions must be verified in the
infrastructure; this repository's workflow does not create or replace them.

Enable controller API access if disabled. The webhook must select exactly one
application; tag/bulk deployment URLs are rejected. The deploy token remains a
team credential, so keep its team membership and lifetime appropriately narrow.

For a controller reachable only from the LAN, set the **repository variable**
`COOLIFY_RUNNER_LABELS` to a JSON array such as
`["self-hosted", "linux", "x64", "coolify-deploy"]`. Use a dedicated deployment
runner restricted to trusted workflows. Only the deploy job runs there; builds
and tests run on GitHub-hosted runners. Never use this runner for untrusted pull
requests. It needs Python setup support, controller access, and access to the app's
HTTPS domain. An existing authenticated SSH tunnel may expose the controller at
`http://127.0.0.1:18000`; plain HTTP is otherwise rejected. Do not expose the
controller publicly just to make the webhook reachable.

## Publish and verify

After the owner reviews and merges the change, open **Actions → Publish to
Coolify → Run workflow**, selecting `main`. Publication is manual. The workflow:

1. Runs the existing quality gate, including privacy, backend, frontend and
   synthetic browser checks.
2. Builds a Linux AMD64 image and starts a disposable container with synthetic
   inputs. It checks login, host/origin restrictions, CSRF, cookie flags, prompt
   checks, the dashboard, and the exclusion of local integration endpoints.
3. Pushes that tested image to GHCR as `sha-<commit>` and `production`.
4. Calls the webhook once, then waits up to ten minutes for two consecutive
   healthy responses bearing the expected commit revision. Redirects are refused
   and controller credentials are never sent to the application health endpoint.

Runs are serialized. `production` is a moving tag, so a manual restart can pick
up its newest image. A queued deployment alone is not success; a timeout remains
unverified and does not automatically retry or roll back. Inspect the deployment
privately in Coolify. For rollback, select a previously published `sha-<commit>`
tag and redeploy; also plan for database compatibility and keep private backups.
Set the image tag back to `production` before the next workflow release.

The build context admits only application/build inputs. The image contains no
provider sessions, models, credentials or seeded demo data. Runtime logs suppress
request-bearing diagnostics. The `/health` endpoint returns only fixed runtime
status fields and the image revision. Cloudflare authenticates external health
requests; other routes also require the hosted gateway login.

## Hosted capabilities and limits

Manual browser prompt checks and stored application views work against data in
this container. The container cannot see prompts or provider sessions on a
visitor's computer. Its provider reader is disabled, its provider home is empty,
and models/desktop extras are absent. Model-assisted commentary stays unavailable
until a separately reviewed runtime design exists. No automatic imports or
provider hooks are configured by deployment.

The gateway strips API tokens and native-presence headers. Browser cookies and
CSRF checks remain enforced; native approval stays unavailable. Protected Agent
effects cannot be approved from this hosted browser. This deployment adds no
remote MCP, generic SQL interface, or remote transcript ingestion interface.

For a local container check, build with a 40-character revision and run
`DEPLOY_REVISION=<same-revision> python scripts/smoke_hosted_container.py` against
the image tagged `prompt-enhancer:candidate`. Docker must be running. This uses
only temporary container storage and synthetic inputs.

## Reference

- [Coolify GitHub Actions integration](https://coolify.io/docs/applications/sources/github/actions)
- [Coolify Docker Image applications](https://coolify.io/docs/applications/deployments/docker-image)
- [Coolify deploy webhooks](https://coolify.io/docs/core/automation/deploy-webhooks)
- [Caddy password authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth)
- [Cloudflare Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
