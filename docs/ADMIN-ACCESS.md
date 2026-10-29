# Private owner administration

The public frontend contains no Admin tab, private admin HTML, owner email or
administration credentials. The private portal is rendered inside the
Cloudflare Worker at `/admin/`. Its only API is the read-only
`GET /api/admin/overview` test-mode summary. Neither route is connected to the
local pool, node, wallet, payouts or server controls.

## Default state: nobody can enter

All three Access variables in `wrangler.worker.toml` are deliberately empty.
Until an owner identity and Cloudflare Access application are configured, every
private request returns `404`, including requests with a plausible email header
or cookie. An empty variable must never be replaced with an inferred identity.

The existing static-only `wrangler.toml` is an optional public Pages deployment.
It does **not** deploy this Worker or make the private portal available. Use
`wrangler.worker.toml` for the current Worker-based deployment.

## Required identity setup

1. Confirm the exact owner login email and the intended admin portal hostname.
   This implementation reserves `/admin` and `/admin/*`, together with
   `/api/admin` and `/api/admin/*`, on the Worker hostname. If a separate portal
   hostname is desired, set up that hostname and its Access application before
   enabling this code there.
2. In Cloudflare Zero Trust, create a self-hosted Access application covering
   both the admin page and private API paths. Use an Allow policy for that exact
   owner email only, with the intended identity provider and MFA requirements.
   Do not add Everyone, email-domain-wide, Bypass or Service Auth policies.
   Confirm the application also covers whichever `workers.dev` or custom
   hostname is being used; protection on one hostname does not set up login on
   another.
3. Copy the Access application audience tag and the team's issuer URL into the
   Worker configuration. The required variables are:

   | Variable | Required value |
   | --- | --- |
   | `ACCESS_TEAM_DOMAIN` | Exact HTTPS issuer, `https://TEAM.cloudflareaccess.com`, without a trailing slash |
   | `ACCESS_AUD` | The one private Access application audience tag |
   | `ADMIN_OWNER_EMAIL` | The confirmed owner login email |

   These values belong only in Worker configuration, never in `VITE_*` settings
   or public assets. The owner email can be stored using a Worker secret to
   avoid putting it in a repository. Remove its empty `[vars]` entry if managing
   it as a secret. Preserve it on subsequent deployments.
4. Build and deploy the complete Worker plus its static assets. Recheck the
   deployed bindings and variables after deployment. The supplied file's empty
   variables are intentionally safe; reusing it without setting real values
   locks everyone out.
5. Verify the public website has no Admin link. A fresh anonymous browser, an
   account with another email, direct API calls and forged email headers must
   never return the private page or summary. The confirmed owner should reach
   the read-only portal only after Access login. Test both public and alternate
   deployment hostnames. The Worker independently rejects missing or invalid
   Access JWTs even when Access policy is absent or bypassed.

## What the server enforces

The Worker accepts identity only from a verified `Cf-Access-Jwt-Assertion`. It
verifies the RS256 signature with WebCrypto using the explicitly configured
team's HTTPS certificate endpoint. It checks the issuer, application audience,
expiry, optional not-before and issued-at claims, subject, and exact owner email
from the signed payload. It never trusts the forwarded email header, an
unsigned cookie, an arbitrary JWT key URL, browser storage or a query flag.

Keys are fetched with a three-second timeout, a 64 KiB body limit, redirect
rejection and at most 16 signing keys. Successful keys are cached for five
minutes; a failed fetch is retried at most every 30 seconds per Worker isolate.
An unknown rotated key is denied until cache refresh, and expired keys are not
reused if Cloudflare cannot be reached. This favors a temporary lockout over
unverified access. No tokens, claims, owner emails or keys are logged.

Private paths always run the Worker before static assets. Percent-encoded paths
that reach the Worker are rejected to avoid path-decoding ambiguities; existing
public assets use plain paths. Browsers or the platform can canonicalize dot
segments before the Worker sees a request; the resulting private route still
requires the same verified owner identity. Only `GET` and `HEAD` are allowed on the exact implemented private
routes. Unknown paths, alternative encodings, failed identity checks and all
write methods return `404`. No private HTML is in the static output, even if the
asset router is invoked directly.

Private responses include `no-store` browser/CDN instructions and no-index
headers. Public and private responses include content-type, frame, referrer,
permissions and CSP protections. The CSP allows existing inline styles, permits
scripts only from this site's own origin, and permits HTTPS API connections.
Narrow `connect-src` to the final API hostname once that URL is chosen. These
headers do not secure the separate local Python API or raw TCP Stratum server;
those services need their own network, authentication and abuse controls.

## Local verification

From the repository root:

```sh
npm run site:build
npm run test:edge
npx wrangler deploy --dry-run --config wrangler.worker.toml
```

The tests use locally generated RSA keys and mocked certificate responses. They
do not contact an identity provider or grant any real account access. They cover
the owner and wrong-owner cases, signature forgery, audience/issuer/time checks,
missing settings, JWKS outages/limits, cache behavior, reserved-route bypasses,
write methods and absence of private HTML in public assets. Real owner login
still needs an end-to-end check after the Access application is configured.

## References

- [Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Cloudflare application tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/)
- [Worker-first static asset routing](https://developers.cloudflare.com/workers/static-assets/routing/worker-script/)
- [Static asset security headers](https://developers.cloudflare.com/workers/static-assets/headers/)
