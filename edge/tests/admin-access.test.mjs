import test from 'node:test'
import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createWorker, SECURITY_HEADERS } from '../worker.mjs'

const nowMs = 1_800_000_000_000
const environment = {
  ACCESS_TEAM_DOMAIN: 'https://test-team.cloudflareaccess.com',
  ACCESS_AUD: 'offline-test-application-audience',
  ADMIN_OWNER_EMAIL: 'owner@example.test',
}
const keyPair = await webcrypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify'])
const wrongPair = await webcrypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify'])
const jwk = { ...await webcrypto.subtle.exportKey('jwk', keyPair.publicKey), kid: 'test-key', use: 'sig', alg: 'RS256' }
const baseClaims = { iss: environment.ACCESS_TEAM_DOMAIN, aud: [environment.ACCESS_AUD], email: environment.ADMIN_OWNER_EMAIL, sub: 'offline-owner-subject', iat: nowMs / 1000 - 10, nbf: nowMs / 1000 - 10, exp: nowMs / 1000 + 600 }
const encode = (value) => Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)).toString('base64url')

async function token(claims = {}, header = {}, signer = keyPair.privateKey) {
  const payload = `${encode({ alg: 'RS256', kid: jwk.kid, typ: 'JWT', ...header })}.${encode({ ...baseClaims, ...claims })}`
  const signature = await webcrypto.subtle.sign('RSASSA-PKCS1-v1_5', signer, new TextEncoder().encode(payload))
  return `${payload}.${Buffer.from(signature).toString('base64url')}`
}

function fixture({ fetchImpl, now = () => nowMs } = {}) {
  const calls = []
  let assetCalls = 0
  const worker = createWorker({
    cryptoImpl: webcrypto,
    now,
    fetchImpl: fetchImpl || (async (url, options) => {
      calls.push({ url, options })
      return Response.json({ keys: [jwk] })
    }),
  })
  const env = { ...environment, ASSETS: { async fetch() { assetCalls++; return new Response('public asset') } } }
  async function request(path = '/admin/', { assertion, headers = {}, method = 'GET', configuration = {} } = {}) {
    if (assertion !== undefined) headers = { 'Cf-Access-Jwt-Assertion': assertion, ...headers }
    return worker.fetch(new Request(`https://pool.example.test${path}`, { method, headers }), { ...env, ...configuration })
  }
  return { worker, request, calls, assetCalls: () => assetCalls }
}

test('only a signature-verified configured owner gets the private Admin tab', async () => {
  const app = fixture()
  const response = await app.request('/admin/', { assertion: await token() })
  assert.equal(response.status, 200)
  assert.match(await response.text(), /href="\/admin\/" aria-current="page">Admin<\/a>/)
  assert.equal(response.headers.get('Cache-Control'), 'private, no-store, max-age=0')
  assert.equal(response.headers.get('CDN-Cache-Control'), 'no-store')
  assert.equal(response.headers.get('X-Robots-Tag'), 'noindex, nofollow, noarchive')
  assert.equal(app.assetCalls(), 0)
  assert.equal(app.calls[0].url, `${environment.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`)
  assert.equal(app.calls[0].options.redirect, 'error')
})

test('private overview contains only honest test-mode data and HEAD has no body', async () => {
  const app = fixture()
  const assertion = await token()
  const response = await app.request('/api/admin/overview', { assertion })
  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), { mode: 'test', access: 'owner-only', administration: 'read-only', payouts: 'disabled', backend: 'not-connected' })
  const head = await app.request('/admin', { assertion, method: 'HEAD' })
  assert.equal(head.status, 200)
  assert.equal(await head.text(), '')
  assert.equal(app.calls.length, 1, 'public signing keys are cached')
})

const deniedClaims = [
  ['another signed-in user', { email: 'someone-else@example.test' }],
  ['wrong issuer', { iss: 'https://other-team.cloudflareaccess.com' }],
  ['wrong audience', { aud: ['other-application-audience'] }],
  ['missing audience', { aud: undefined }],
  ['expired token', { exp: nowMs / 1000 }],
  ['missing expiry', { exp: undefined }],
  ['string expiry', { exp: String(nowMs / 1000 + 600) }],
  ['future not-before', { nbf: nowMs / 1000 + 1 }],
  ['invalid not-before', { nbf: 'yesterday' }],
  ['future issuance', { iat: nowMs / 1000 + 1 }],
  ['missing subject', { sub: undefined }],
  ['missing signed email', { email: undefined }],
]
for (const [name, claims] of deniedClaims) test(`denies ${name}`, async () => {
  const app = fixture()
  const response = await app.request('/admin/', { assertion: await token(claims), headers: { 'Cf-Access-Authenticated-User-Email': environment.ADMIN_OWNER_EMAIL } })
  assert.equal(response.status, 404)
  assert.equal(await response.text(), 'Not found')
  assert.equal(app.assetCalls(), 0)
})

test('anonymous and forged email, authorization, cookie, query, and role flags do not grant access', async () => {
  const app = fixture()
  const assertion = await token()
  for (const headers of [
    {},
    { 'Cf-Access-Authenticated-User-Email': environment.ADMIN_OWNER_EMAIL },
    { Authorization: `Bearer ${assertion}` },
    { Cookie: `CF_Authorization=${assertion}; isAdmin=true; email=${environment.ADMIN_OWNER_EMAIL}` },
    { 'X-Admin': 'true', 'X-User-Role': 'admin' },
  ]) {
    const response = await app.request('/admin/?admin=true&email=owner%40example.test', { headers })
    assert.equal(response.status, 404)
    assert.equal(await response.text(), 'Not found')
  }
  assert.equal(app.calls.length, 0)
})

test('a forged owner payload, foreign signature and unsigned/unsupported JWTs are denied', async () => {
  const app = fixture()
  const otherToken = await token({ email: 'someone-else@example.test' })
  const parts = otherToken.split('.')
  parts[1] = encode(baseClaims)
  for (const assertion of [
    parts.join('.'),
    await token({}, {}, wrongPair.privateKey),
    await token({}, { alg: 'HS256' }),
    await token({}, { alg: 'none' }),
    await token({}, { kid: 'missing-key' }),
    await token({}, { jku: 'https://attacker.example/jwks' }),
    await token({}, { crit: ['made-up-extension'] }),
    'not-a-token',
    `${encode({ alg: 'none' })}.${encode(baseClaims)}.`,
    'a'.repeat(16 * 1024 + 1),
  ]) assert.equal((await app.request('/admin/', { assertion })).status, 404)
})

test('all missing or invalid owner configuration fails closed without fetching keys', async () => {
  const app = fixture()
  const assertion = await token()
  const changes = [
    { ACCESS_TEAM_DOMAIN: '' }, { ACCESS_AUD: '' }, { ADMIN_OWNER_EMAIL: '' },
    { ACCESS_TEAM_DOMAIN: 'https://attacker.example' },
    { ACCESS_TEAM_DOMAIN: 'https://test-team.cloudflareaccess.com@attacker.example' },
    { ACCESS_TEAM_DOMAIN: 'http://test-team.cloudflareaccess.com' },
    { ACCESS_TEAM_DOMAIN: 'https://test-team.cloudflareaccess.com/' },
    { ACCESS_AUD: '*' }, { ADMIN_OWNER_EMAIL: '*' },
  ]
  for (const configuration of changes) assert.equal((await app.request('/admin/', { assertion, configuration })).status, 404)
  assert.equal(app.calls.length, 0)
})

test('private routes cannot fall through to assets, use alternate encodings, or mutate state', async () => {
  const app = fixture()
  const assertion = await token()
  for (const path of [
    '/admin/index.html', '/admin/anything', '/api/admin', '/api/admin/', '/api/admin/payout',
    '/Admin/', '/API/ADMIN/overview', '/admin//', '/admin/overview',
    '/%61dmin/', '/ad%6din/', '/admin%2f', '/admin%252findex.html', '/api%2fadmin/overview',
    '/api/ad%6din/overview', '/%2561dmin/', '/admin/%5cindex.html',
  ]) {
    assert.equal((await app.request(path, { assertion })).status, 404, path)
    assert.equal((await app.request(path)).status, 404, `anonymous ${path}`)
  }
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
    assert.equal((await app.request('/admin/', { assertion, method })).status, 404, method)
    assert.equal((await app.request('/api/admin/overview', { assertion, method })).status, 404, method)
  }
  assert.equal(app.assetCalls(), 0)
})

test('URL-normalized dot segments still require owner verification', async () => {
  const app = fixture()
  for (const path of ['/admin/%2e%2e/admin/', '/public/../admin/', '/api/public/../admin/overview']) {
    assert.equal((await app.request(path)).status, 404)
    assert.equal((await app.request(path, { assertion: await token({ email: 'other@example.test' }) })).status, 404)
    assert.equal((await app.request(path, { assertion: await token() })).status, 200)
  }
  assert.equal(app.assetCalls(), 0)
})

test('JWKS failures fail closed and retries are bounded', async () => {
  let requests = 0
  const app = fixture({ fetchImpl: async () => { requests++; throw new Error('network unavailable') } })
  const assertion = await token()
  for (let i = 0; i < 5; i++) assert.equal((await app.request('/admin/', { assertion })).status, 404)
  assert.equal(requests, 1)
})

test('JWKS expiry, malformed keys, redirects and oversized documents fail closed', async () => {
  const assertion = await token()
  for (const response of [
    new Response(null, { status: 302, headers: { Location: 'https://attacker.example' } }),
    Response.json({ keys: [] }),
    Response.json({ keys: [jwk, jwk] }),
    Response.json({ keys: [{ ...jwk, kty: 'oct' }] }),
    Response.json({ keys: [{ ...jwk, use: 'enc' }] }),
    new Response('{broken json'),
    new Response('x'.repeat(64 * 1024 + 1)),
    new Response('{}', { headers: { 'Content-Length': '1000000' } }),
  ]) {
    const app = fixture({ fetchImpl: async () => response })
    assert.equal((await app.request('/admin/', { assertion })).status, 404)
  }
  let clock = nowMs
  let requests = 0
  const app = fixture({ now: () => clock, fetchImpl: async () => {
    requests++
    if (requests > 1) throw new Error('offline after expiration')
    return Response.json({ keys: [jwk] })
  } })
  assert.equal((await app.request('/admin/', { assertion })).status, 200)
  clock += 5 * 60 * 1000 + 1
  assert.equal((await app.request('/admin/', { assertion })).status, 404, 'expired keys are never reused on a fetch failure')
})

test('concurrent requests share a single bounded key fetch', async () => {
  const app = fixture()
  const assertion = await token()
  const responses = await Promise.all(Array.from({ length: 8 }, () => app.request('/admin/', { assertion })))
  assert.ok(responses.every((response) => response.status === 200))
  assert.equal(app.calls.length, 1)
})

test('public responses preserve assets and have the same hardening headers', async () => {
  const app = fixture()
  const response = await app.request('/')
  assert.equal(response.status, 200)
  assert.equal(await response.text(), 'public asset')
  assert.equal(app.assetCalls(), 1)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(response.headers.get(name), value)
  assert.equal(response.headers.get('Content-Security-Policy').includes("script-src 'self'"), true)
  assert.equal(response.headers.get('Content-Security-Policy').includes("script-src 'self' 'unsafe-inline'"), false)
})

async function allFiles(directory) {
  const files = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'tests' || entry.name === '_site') continue
    const path = `${directory}/${entry.name}`
    if (entry.isDirectory()) files.push(...await allFiles(path))
    else files.push(path)
  }
  return files
}

test('private portal is absent from public source and build assets; headers are copied', async () => {
  const root = fileURLToPath(new URL('../../', import.meta.url))
  const directories = [`${root}site`]
  if (existsSync(`${root}site/_site`)) directories.push(`${root}site/_site`)
  for (const directory of directories) {
    for (const path of await allFiles(directory)) {
      if (!/\.(?:html|js|css|mjs)$/.test(path)) continue
      const text = await readFile(path, 'utf8')
      assert.doesNotMatch(text, /href\s*=\s*["'][^"']*\/admin(?:\/|["'])/i, path)
      assert.doesNotMatch(text, /PRIVATE PORTAL|VERIFIED OWNER ACCESS|Signed in as/, path)
    }
  }
  const sourceHeaders = await readFile(`${root}site/public/_headers`, 'utf8')
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.ok(sourceHeaders.includes(`${name}: ${value}`), name)
  if (existsSync(`${root}site/_site`)) assert.equal(await readFile(`${root}site/_site/_headers`, 'utf8'), sourceHeaders)
  const wrangler = await readFile(`${root}wrangler.worker.toml`, 'utf8')
  assert.match(wrangler, /main = "\.\/edge\/worker\.mjs"/)
  assert.match(wrangler, /binding = "ASSETS"/)
  assert.match(wrangler, /run_worker_first = \["\/admin\*", "\/api\/admin\*", "\/\*%\*"\]/)
  for (const key of Object.keys(environment)) assert.ok(wrangler.includes(`${key} = ""`), `${key} defaults to no access`)
})
