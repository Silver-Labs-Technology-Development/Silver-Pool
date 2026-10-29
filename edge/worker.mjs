import { renderAdmin } from './private-admin.mjs'

export const SECURITY_HEADERS = Object.freeze({
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https:; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'; upgrade-insecure-requests",
})

const encoder = new TextEncoder()
const decoder = new TextDecoder('utf-8', { fatal: true })
const KEY_TTL_MS = 5 * 60 * 1000
const RETRY_MS = 30 * 1000
const MAX_JWKS_BYTES = 64 * 1024
const JWT_MAX_BYTES = 16 * 1024

function accessConfiguration(env) {
  const domain = env.ACCESS_TEAM_DOMAIN
  const audience = env.ACCESS_AUD
  const email = env.ADMIN_OWNER_EMAIL
  // Use only the explicitly configured tenant. A token cannot choose its JWKS
  // host through its issuer, jku, x5u or any other untrusted field.
  if (typeof domain !== 'string' || !/^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/.test(domain)) return null
  if (typeof audience !== 'string' || !/^[A-Za-z0-9_-]{8,256}$/.test(audience)) return null
  if (typeof email !== 'string' || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null
  return { issuer: domain, audience, email: email.toLowerCase() }
}

function decodeSegment(segment) {
  if (!segment || !/^[A-Za-z0-9_-]+$/.test(segment)) throw new Error('Malformed token')
  const binary = atob(segment.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

function decodeObject(segment) {
  const object = JSON.parse(decoder.decode(decodeSegment(segment)))
  if (!object || typeof object !== 'object' || Array.isArray(object)) throw new Error('Malformed token')
  return object
}

async function boundedJson(response) {
  if (!response.ok || !response.body) throw new Error('Keys unavailable')
  const contentLength = Number(response.headers.get('Content-Length'))
  if (contentLength > MAX_JWKS_BYTES) throw new Error('Keys too large')
  const reader = response.body.getReader()
  const chunks = []
  let length = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (length > MAX_JWKS_BYTES) throw new Error('Keys too large')
      chunks.push(value)
    }
  } catch (error) {
    await reader.cancel().catch(() => {})
    throw error
  } finally {
    reader.releaseLock()
  }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return JSON.parse(decoder.decode(bytes))
}

function privateResponse(body = 'Not found', status = 404, contentType = 'text/plain; charset=utf-8', method = 'GET') {
  return new Response(method === 'HEAD' ? null : body, {
    status,
    headers: {
      ...SECURITY_HEADERS,
      'Content-Type': contentType,
      'Cache-Control': 'private, no-store, max-age=0',
      'CDN-Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow, noarchive',
      Vary: 'Cf-Access-Jwt-Assertion, Cookie',
    },
  })
}

// Dependency injection is exclusively for offline cryptographic tests. Runtime
// verification always uses WebCrypto and the configured Cloudflare tenant.
export function createWorker({ fetchImpl = globalThis.fetch, now = Date.now, cryptoImpl = globalThis.crypto } = {}) {
  const tenants = new Map()

  async function keyFor(issuer, kid) {
    let entry = tenants.get(issuer)
    if (!entry) {
      if (tenants.size >= 4) tenants.delete(tenants.keys().next().value)
      entry = { keys: new Map(), expires: 0, retryAt: 0, pending: null }
      tenants.set(issuer, entry)
    }
    const time = now()
    if (time < entry.expires) return entry.keys.get(kid) || null
    if (entry.pending) { await entry.pending; return entry.keys.get(kid) || null }
    if (time < entry.retryAt) return null
    entry.retryAt = time + RETRY_MS
    entry.pending = (async () => {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 3000)
      try {
        const response = await fetchImpl(`${issuer}/cdn-cgi/access/certs`, {
          signal: controller.signal, redirect: 'error', headers: { Accept: 'application/json' },
        })
        const document = await boundedJson(response)
        if (!document || !Array.isArray(document.keys) || document.keys.length > 16) throw new Error('Invalid keys')
        const keys = new Map()
        for (const jwk of document.keys) {
          if (!jwk || jwk.kty !== 'RSA' || typeof jwk.kid !== 'string' || jwk.kid.length > 256) continue
          if ((jwk.alg && jwk.alg !== 'RS256') || (jwk.use && jwk.use !== 'sig') || jwk.d) continue
          if (keys.has(jwk.kid)) throw new Error('Duplicate key identifier')
          const key = await cryptoImpl.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify'])
          if (key.algorithm.modulusLength < 2048) throw new Error('Weak key')
          keys.set(jwk.kid, key)
        }
        if (!keys.size) throw new Error('No signing keys')
        entry.keys = keys
        entry.expires = now() + KEY_TTL_MS
      } catch {
        // Expired keys and network errors never grant access.
        entry.keys.clear()
        entry.expires = 0
      } finally {
        clearTimeout(timeout)
        entry.pending = null
      }
    })()
    await entry.pending
    return entry.keys.get(kid) || null
  }

  async function verifyOwner(request, configuration) {
    try {
      // A forwarded email, cookie or client-side flag is not an identity proof.
      const token = request.headers.get('Cf-Access-Jwt-Assertion')
      if (!token || token.length > JWT_MAX_BYTES) return null
      const parts = token.split('.')
      if (parts.length !== 3) return null
      const header = decodeObject(parts[0])
      const claims = decodeObject(parts[1])
      if (header.alg !== 'RS256' || typeof header.kid !== 'string' || !header.kid || header.kid.length > 256) return null
      if (header.crit !== undefined || header.jku !== undefined || header.jwk !== undefined || header.x5u !== undefined) return null
      const seconds = Math.floor(now() / 1000)
      if (claims.iss !== configuration.issuer || !Number.isSafeInteger(claims.exp) || claims.exp <= seconds) return null
      if (claims.nbf !== undefined && (!Number.isSafeInteger(claims.nbf) || claims.nbf > seconds)) return null
      if (claims.iat !== undefined && (!Number.isSafeInteger(claims.iat) || claims.iat > seconds)) return null
      const audiences = typeof claims.aud === 'string' ? [claims.aud] : claims.aud
      if (!Array.isArray(audiences) || !audiences.every((value) => typeof value === 'string') || !audiences.includes(configuration.audience)) return null
      if (typeof claims.email !== 'string' || claims.email.toLowerCase() !== configuration.email) return null
      if (typeof claims.sub !== 'string' || !claims.sub) return null
      const key = await keyFor(configuration.issuer, header.kid)
      if (!key) return null
      const valid = await cryptoImpl.subtle.verify('RSASSA-PKCS1-v1_5', key, decodeSegment(parts[2]), encoder.encode(`${parts[0]}.${parts[1]}`))
      return valid ? { email: claims.email } : null
    } catch { return null }
  }

  return {
    async fetch(request, env) {
      const { pathname } = new URL(request.url)
      // No percent-encoded path is forwarded to assets: this removes ambiguous
      // encoded slashes, backslashes, double encoding and encoded route names.
      // All current public asset names are plain ASCII and need no encoding.
      if (pathname.includes('%')) return privateResponse(undefined, 404, undefined, request.method)
      const reserved = /^\/(?:admin|api\/admin)(?:\/|$)/i.test(pathname)
      if (reserved) {
        const configuration = accessConfiguration(env)
        if (!configuration) return privateResponse(undefined, 404, undefined, request.method)
        const identity = await verifyOwner(request, configuration)
        if (!identity) return privateResponse(undefined, 404, undefined, request.method)
        if (!['GET', 'HEAD'].includes(request.method)) return privateResponse(undefined, 404, undefined, request.method)
        if (pathname === '/admin' || pathname === '/admin/') {
          return privateResponse(renderAdmin(identity.email), 200, 'text/html; charset=utf-8', request.method)
        }
        if (pathname === '/api/admin/overview') {
          return privateResponse(JSON.stringify({ mode: 'test', access: 'owner-only', administration: 'read-only', payouts: 'disabled', backend: 'not-connected' }), 200, 'application/json; charset=utf-8', request.method)
        }
        return privateResponse(undefined, 404, undefined, request.method)
      }
      // No private template is ever passed to ASSETS. Missing public documents
      // can fall back here after Cloudflare's asset-first router.
      const response = env.ASSETS ? await env.ASSETS.fetch(request) : new Response('Not found', { status: 404 })
      const headers = new Headers(response.headers)
      for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value)
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
    },
  }
}

export default createWorker()
