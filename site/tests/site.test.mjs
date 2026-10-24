import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8')
const pagesWorkflow = await readFile(new URL('../../.github/workflows/pages.yml', import.meta.url), 'utf8')

const expectedSections = ['home', 'mining', 'statistics', 'workers', 'blocks', 'fees', 'coins', 'docs']

test('all primary navigation sections exist and navigation links resolve', () => {
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]))
  for (const section of expectedSections) assert.ok(ids.has(section), `missing #${section}`)
  for (const [, href] of html.matchAll(/\bhref="#([^"]+)"/g)) {
    assert.ok(ids.has(href), `unresolved in-page link #${href}`)
  }
})

test('Silver Pool branding is present', () => {
  assert.match(html, /Silver Pool/)
  assert.match(html, /Bitcoin Silver Mining Pool/)
  assert.match(html, /SILVER <span>POOL<\/span>/)
})

test('pool statistics do not claim live data', () => {
  assert.match(html, /Not connected/)
  assert.match(html, /Data unavailable/)
})

test('CSS has responsive and accessibility foundations', () => {
  assert.match(css, /@media \(max-width: 640px\)/)
  assert.match(css, /:focus-visible/)
  assert.match(html, /<html lang="en">/)
  assert.match(html, /name="viewport"/)
  assert.match(html, /class="skip-link" href="#main"/)
})

test('Pages workflow validates tests and deploys', () => {
  assert.match(pagesWorkflow, /node --test tests\/\*\.test\.mjs/)
  assert.match(pagesWorkflow, /pages: write/)
  assert.match(pagesWorkflow, /id-token: write/)
  assert.match(pagesWorkflow, /path: site\/_site/)
})

test('no invented live statistics', () => {
  assert.doesNotMatch(html, /Hashrate: [1-9]/)
  assert.doesNotMatch(html, /Active Miners: [1-9]/)
})