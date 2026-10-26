import assert from 'node:assert/strict'
import { readFile, stat } from 'node:fs/promises'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, test } from 'node:test'

const siteRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const repoRoot = resolve(siteRoot, '..')

const pages = [
  ['index.html', 'overview', 'Overview — Silver Pool', 'Mine Bitcoin Silver.'],
  ['statistics/index.html', 'statistics', 'Statistics — Silver Pool', 'Hashrate and share history'],
  ['miners/index.html', 'miners', 'Miners — Silver Pool', 'Search the pool'],
  ['miner/index.html', 'miners', 'Miner detail — Silver Pool', 'Miner and worker records'],
  ['blocks/index.html', 'blocks', 'Blocks — Silver Pool', 'Blocks found by Silver Pool'],
  ['getting-started/index.html', 'getting-started', 'Getting Started — Silver Pool', 'Connect a BTCS miner'],
  ['pool/index.html', 'pool', 'Pool Configuration — Silver Pool', 'Fees, rewards and payout policy'],
  ['api-docs/index.html', 'api-docs', 'API Documentation — Silver Pool', 'Read-only pool API'],
  ['status/index.html', 'status', 'Service Status — Silver Pool', 'Is the pool ready?'],
  ['help/index.html', 'help', 'Help &amp; Troubleshooting — Silver Pool', 'Diagnose a connection problem'],
]

const navPages = [
  'overview',
  'statistics',
  'miners',
  'blocks',
  'getting-started',
  'pool',
  'api-docs',
  'status',
  'help',
]

function decodeEntities(value) {
  return value
    .replaceAll('&amp;', '&')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
}

async function readPage(relative) {
  return readFile(join(siteRoot, relative), 'utf8')
}

function attribute(tag, name) {
  const match = tag.match(new RegExp(`${name}="([^"]*)"`, 'i'))
  return match ? decodeEntities(match[1]) : null
}

async function fileExists(path) {
  try {
    const info = await stat(path)
    return info.isFile()
  } catch {
    return false
  }
}

async function resolveInternalTarget(pageRelative, target) {
  const clean = target.split('#')[0].split('?')[0]
  if (!clean) return null
  if (/^(?:[a-z]+:|\/\/)/i.test(clean)) return null
  if (clean.startsWith('data:')) return null
  // API URLs are served by the backend, not by the static site.
  if (clean === '/api' || clean.startsWith('/api/') || clean.includes('/api/')) return null
  const base = dirname(join(siteRoot, pageRelative))
  let candidate = resolve(base, clean)
  if (!candidate.startsWith(siteRoot)) return null
  if (await fileExists(candidate)) return candidate
  if (await fileExists(join(candidate, 'index.html'))) return join(candidate, 'index.html')
  if (!extname(candidate) && (await fileExists(`${candidate}.html`))) return `${candidate}.html`
  return candidate
}

describe('static multi-page site', () => {
  test('every route has a unique title, description, one h1 and the expected page marker', async () => {
    const titles = new Set()
    const descriptions = new Set()
    for (const [relative, marker, title, heading] of pages) {
      const html = await readPage(relative)
      assert.equal((html.match(/<title>/g) || []).length, 1, `${relative} title count`)
      assert.equal((html.match(/<h1[\s>]/g) || []).length, 1, `${relative} must have one h1`)
      const pageTitle = html.match(/<title>([^<]*)<\/title>/)?.[1]
      assert.equal(pageTitle, title, `${relative} title`)
      assert.ok(!titles.has(pageTitle), `${relative} has a duplicate title`)
      titles.add(pageTitle)

      const description = html.match(/<meta\s+name="description"\s+content="([^"]+)"/i)?.[1]
      assert.ok(description && description.length > 40, `${relative} needs a description`)
      assert.ok(!descriptions.has(description), `${relative} has a duplicate description`)
      descriptions.add(description)

      assert.match(html, new RegExp(`<body[^>]*data-page="${marker}"`), `${relative} body marker`)
      const h1 = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1] || ''
      assert.ok(
        decodeEntities(h1.replace(/<[^>]+>/g, '')).includes(decodeEntities(heading)),
        `${relative} heading was ${h1}`,
      )
      assert.match(
        html,
        /<meta\s+name="viewport"\s+content="width=device-width, initial-scale=1"/i,
        `${relative} mobile viewport`,
      )
      assert.match(html, /<script\s+type="module"\s+src="[^"]+\.js"/, `${relative} module entry`)
      assert.match(html, /aria-live="polite"/, `${relative} live state region`)
    }
    assert.equal(titles.size, pages.length)
  })

  test('each page includes the full primary navigation with exactly one active entry', async () => {
    for (const [relative, marker] of pages) {
      const html = await readPage(relative)
      const nav = html.match(/<nav[^>]*data-nav[^>]*>([\s\S]*?)<\/nav>/)?.[1]
      assert.ok(nav, `${relative} navigation`)
      const entries = [...nav.matchAll(/<a\s[^>]*href="([^"]+)"[^>]*data-page="([^"]+)">([^<]+)<\/a>/g)]
      assert.deepEqual(
        entries.map((entry) => entry[2]),
        navPages,
        `${relative} navigation order`,
      )
      for (const [, href, dataPage, label] of entries) {
        const resolved = await resolveInternalTarget(relative, href)
        assert.ok(
          resolved && (await fileExists(resolved)),
          `${relative} navigation ${label} -> ${href} did not resolve`,
        )
        const linked = await readFile(resolved, 'utf8')
        assert.equal(
          linked.match(/<body[^>]*data-page="([^"]+)"/)?.[1],
          dataPage,
          `${relative} navigation label ${label} points at the wrong page`,
        )
      }
      // The active class is applied by the shared runtime module, so static
      // documents must not hardcode a second source of truth.
      assert.ok(!nav.includes('is-active'), `${relative} must not hardcode an active nav link`)
    }
  })

  test('all internal links and asset references resolve to files', async () => {
    for (const [relative] of pages) {
      const html = await readPage(relative)
      const references = [
        ...html.matchAll(/(?:href|src)="([^"]+)"/g),
        ...html.matchAll(/srcset="([^"]+)"/g),
      ]
      for (const match of references) {
        const value = decodeEntities(match[1])
        if (value.startsWith('#')) continue
        const resolved = await resolveInternalTarget(relative, value)
        if (!resolved) continue
        assert.ok(
          await fileExists(resolved),
          `${relative} references missing internal target ${value} (${resolved})`,
        )
      }
    }
  })

  test('no fake pool endpoints, placeholder statistics or payout claims', async () => {
    const forbidden = [
      'stratum.silver-pool.example',
      'pool.example',
      'example.com',
      'example.org',
      'lorem ipsum',
      'TODO',
      'FIXME',
    ]
    for (const [relative] of pages) {
      const html = await readPage(relative)
      for (const value of forbidden) {
        assert.ok(!html.toLowerCase().includes(value.toLowerCase()), `${relative} contains ${value}`)
      }
    }
    for (const asset of await readFile(join(siteRoot, 'assets', 'site.js'), 'utf8')
      .then(() => ['site.js', 'overview.js', 'statistics.js', 'miners.js', 'miner.js', 'blocks.js', 'getting-started.js', 'pool.js', 'api-docs.js', 'status.js', 'help.js'])) {
      const source = await readFile(join(siteRoot, 'assets', asset), 'utf8')
      for (const value of ['stratum.silver-pool.example', 'pool.example', 'example.com']) {
        assert.ok(!source.includes(value), `assets/${asset} contains ${value}`)
      }
    }
    for (const [relative] of pages) {
      const lower = (await readPage(relative)).toLowerCase()
      assert.ok(
        !/payouts?\s+(?:are|is)\s+(?:enabled|live|active)/.test(lower),
        `${relative} must not claim payouts are enabled`,
      )
    }
  })

  test('shared modules are imported by pages and never reference deleted single-page files', async () => {
    const deleted = ['site.mjs', 'projects.mjs', 'site.test.mjs']
    for (const [relative] of pages) {
      const html = await readPage(relative)
      for (const value of deleted) {
        assert.ok(!html.includes(value), `${relative} references deleted ${value}`)
      }
    }
    for (const asset of ['overview.js', 'statistics.js', 'miners.js', 'miner.js', 'blocks.js', 'getting-started.js', 'pool.js', 'api-docs.js', 'status.js', 'help.js']) {
      const source = await readFile(join(siteRoot, 'assets', asset), 'utf8')
      assert.match(source, /from '\.\/site\.js'/, `assets/${asset} must use the shared module`)
    }
  })

  test('built output contains every route and no dangling internal assets', async (t) => {
    const builtRoot = join(siteRoot, '_site')
    if (!(await fileExists(join(builtRoot, 'index.html')))) {
      t.skip('run npm run build before the built-output check')
      return
    }
    for (const [relative] of pages) {
      const built = join(builtRoot, relative)
      assert.ok(await fileExists(built), `built output is missing ${relative}`)
      const html = await readFile(built, 'utf8')
      const references = [...html.matchAll(/(?:href|src)="([^"]+)"/g)].map((match) =>
        decodeEntities(match[1]),
      )
      for (const reference of references) {
        if (
          reference.startsWith('#') ||
          reference.startsWith('data:') ||
          /^(?:[a-z]+:|\/\/)/i.test(reference) ||
          reference.startsWith('/api') ||
          reference.startsWith('../api') ||
          reference.startsWith('api/')
        ) {
          continue
        }
        const path = reference.split('#')[0].split('?')[0]
        let candidate = path.startsWith('/')
          ? resolve(builtRoot, `.${path}`)
          : resolve(dirname(built), path)
        if (!(await fileExists(candidate)) && path.startsWith('/')) {
          // SITE_BASE builds (for example /Silver-Pool/) prefix root-relative
          // asset URLs with the deployment subpath but still write files at
          // the output root. Accept that layout while keeping root builds strict.
          const segments = path.split('/').filter(Boolean)
          if (segments.length > 1) {
            candidate = resolve(builtRoot, ...segments.slice(1))
          }
        }
        if (candidate.endsWith('/')) candidate = join(candidate, 'index.html')
        if (!(await fileExists(candidate))) {
          assert.ok(
            await fileExists(join(candidate, 'index.html')),
            `${relative} built reference ${reference} is missing`,
          )
        }
      }
      assert.ok(!html.includes('site.mjs'), `${relative} still references site.mjs`)
      assert.ok(!html.includes('projects.mjs'), `${relative} still references projects.mjs`)
    }
  })

  test('Vite inputs list every HTML page and each input exists', async () => {
    const config = await readFile(join(siteRoot, 'vite.config.js'), 'utf8')
    for (const [relative] of pages) {
      assert.ok(config.includes(`'${relative}'`), `vite.config.js is missing ${relative}`)
      assert.ok(await fileExists(join(siteRoot, relative)), `missing Vite input ${relative}`)
    }
    const declared = [...config.matchAll(/'([^']+\/index\.html|index\.html)'/g)].map((match) => match[1])
    assert.equal(new Set(declared).size, pages.length, 'Vite declares duplicate inputs')
  })

  test('package scripts expose static, browser, dev and production build checks', async () => {
    const packageJson = JSON.parse(await readFile(join(siteRoot, 'package.json'), 'utf8'))
    assert.match(packageJson.scripts.build, /vite build/)
    assert.match(packageJson.scripts.dev, /serve\.mjs/)
    assert.match(packageJson.scripts['test:browser'], /browser\.test\.mjs/)
    assert.match(packageJson.scripts['test:static'], /static\.test\.mjs/)
    assert.match(packageJson.scripts.test, /static\.test\.mjs/)
    const rootPackage = JSON.parse(await readFile(join(repoRoot, 'package.json'), 'utf8'))
    assert.match(rootPackage.scripts['site:build'], /npm run build/)
    assert.match(rootPackage.scripts['site:test'], /npm test/)
    assert.match(rootPackage.scripts['site:test:browser'], /test:browser/)
  })
})
