# Repository Audit — Silver Pool

> **Historical snapshot — superseded by
> [`docs/IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md) (2026-10-26).**
>
> The file locations and Git state below are from the earlier audit. References
> to `site/projects.mjs`, `site/site.mjs` and `site/tests/site.test.mjs` are
> obsolete: those single-page files were removed and replaced by the ten-route
> site in `site/`. Do not use this document as current build or deployment
> guidance.


This document records the state of the Silver Pool project and its repository boundaries as of the audit date. It is intended to prevent misplacement of pool content and to serve as the reference for the repair-and-implementation work.

## Source Locations (as of audit)

| File / Directory | Current Location | Intended Destination | Status |
|---|---|---|---|
| `site/index.html` | `~/Silver-Labs/Silver-Pool/site/index.html` | `Silver-Pool/site/index.html` | ✅ In place |
| `site/projects.mjs` | `~/Silver-Labs/Silver-Pool/site/projects.mjs` | `Silver-Pool/site/projects.mjs` | ✅ In place |
| `site/site.mjs` | `~/Silver-Labs/Silver-Pool/site/site.mjs` | `Silver-Pool/site/site.mjs` | ✅ In place |
| `site/styles.css` | `~/Silver-Labs/Silver-Pool/site/styles.css` | `Silver-Pool/site/styles.css` | ✅ In place |
| `site/vite.config.js` | `~/Silver-Labs/Silver-Pool/site/vite.config.js` | `Silver-Pool/site/vite.config.js` | ✅ In place |
| `site/package.json` | `~/Silver-Labs/Silver-Pool/site/package.json` | `Silver-Pool/site/package.json` | ✅ In place |
| `site/package-lock.json` | `~/Silver-Labs/Silver-Pool/site/package-lock.json` | `Silver-Pool/site/package-lock.json` | ✅ In place |
| `site/tests/site.test.mjs` | `~/Silver-Labs/Silver-Pool/site/tests/site.test.mjs` | `Silver-Pool/site/tests/site.test.mjs` | ✅ In place |
| `site/scripts/serve.mjs` | `~/Silver-Labs/Silver-Pool/site/scripts/serve.mjs` | `Silver-Pool/site/scripts/serve.mjs` | ✅ In place |

## Misplaced / Duplicate Files

| File | Current Location | Issue | Action |
|---|---|---|---|
| Pool website `index.html` | Previously in `Official-Website/` root | `Official-Website/website-development` branch had pool content replacing Silver Labs homepage | ✅ Restored — `website-development` branch now contains original Silver Labs homepage; pool UI moved to `Silver-Pool/site/` |
| Pool `projects.mjs` | Previously in `Official-Website/` root | Same as above | ✅ Restored — `projects.mjs` in Official-Website now reflects Silver Labs projects, not pool |
| Pool test references | Previously in `Official-Website/` | Navigation and test expectations included pool content in Silver Labs site | ✅ Fixed — `website-development` branch tests reference Silver Labs navigation |

## Repository Boundaries

### Silver-Pool (canonical home for pool product)

**Contains:**
- Pool Python backend: `src/btcs_pool/`, `tests/`
- Pool frontend: `site/`, `.github/workflows/`
- Pool documentation: `README.md`, `RELEASE_CHECKLIST.md`, `SECURITY.md`, `docs/`
- Pool configuration: `.gitignore`

**Does NOT contain:**
- Silver Labs corporate website content
- Silver-Scan, SilverPay, SilverForge-Studio, btcs-l2, SilvEx products

### Official-Website (Silver Labs corporate/developer website only)

**Contains:**
- Silver Labs homepage with Ecosystem, Architecture, Roadmap, Developers, About navigation
- Silver Labs project status listings (SilverPay, SilverForge-Studio, btcs-l2, etc.)
- Silver Labs visual identity (navy structure, bright blue accents)
- Developer quickstart commands
- No pool mining interface

**Does NOT contain:**
- Pool Stratum configuration
- Pool miner instructions
- Pool fee/payout statistics
- Pool worker/dashboard data

### Silver-Scan (planning repository only)

**Contains:**
- README, LICENSE, SECURITY.md, ARCHITECTURE.md
- Planning scope documents — no code, no explorer/indexer, no web interface

**Status:** Untouched — remains as planning repository only.

## Git State Summary

| Repository | Branch | HEAD SHA | Remote | Status |
|---|---|---|---|---|
| **Silver-Pool** | main | `ad3ca578773dde9e542b3b02f861eeca49b00b42` | `origin` at `https://github.com/Silver-Labs-Technology-Development/Silver-Pool.git` | `site/` directory committed and pushed. `.github/workflows/pages.yml` committed locally (commit `13f5f45`) but **not pushed** — requires GitHub web UI or PAT with `workflow` scope to add. |
| **Official-Website** | website-development | `64e069f5f4ae9d7f1591126de4dd9f37fd279c86` | `origin` at `https://github.com/Silver-Labs-Technology-Development/Official-Website.git` | ✅ `website-development` branch restored with original Silver Labs homepage. `main` branch has SilverPay description. |
| **Official-Website** | main | `e1456afedd9fddecf169712b7342cfe991cf1ac7` | Same remote | ✅ Original SilverPay wallet description — not modified. |
| **Silver-Scan** | main | (verified) | Same remote | ✅ Untouched — planning repository only. |

## Audit Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `.github/workflows/pages.yml` not pushed to remote | GitHub Pages deployment workflow unavailable | Add workflow via GitHub web UI: Settings → Pages → Deploy from branch `main`; or use PAT with `workflow` scope to push |
| `site/_site/` in git history | Generated build output tracked in git | `_site/` already in `.gitignore`; `package-lock.json` tracked as snapshot of `npm ci` output |
| Pool frontend references `127.0.0.1` example endpoints | May imply live service availability | All example endpoints marked as "replace when deployed"; no live data displayed; dashboard shows "Not connected" / "Data unavailable" states |
| Official-Website branch confusion | `website-development` might accidentally get pool content reapplied | Branch already restored; audit document records the fix; no further force-pushes planned |

## Action Items

1. Add `.github/workflows/pages.yml` to Silver-Pool remote via GitHub web UI or PAT push
2. Verify `npm ci && node --test tests/*.test.mjs && npm run build` passes in `site/`
3. Verify Official-Website `website-development` branch has original Silver Labs homepage (already completed)
4. Verify Silver-Pool website builds and `_site/` outputs correctly with `/Silver-Pool/` base path
5. Do NOT force-push or delete any branches in Official-Website
6. Do NOT merge pool content into Official-Website
7. Document any incomplete release gates and blockers in final report