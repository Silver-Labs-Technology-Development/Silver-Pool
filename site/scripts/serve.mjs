import { createServer, request as httpRequest } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const defaultRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const root = resolve(process.env.SITE_ROOT || defaultRoot)
const port = Number(process.env.PORT ?? process.env.SILVER_POOL_HTTP_PORT ?? 4173)
const host = process.env.HOST || process.env.SILVER_POOL_HTTP_BIND || '127.0.0.1'
const defaultApiProxy = `http://${process.env.BTCS_POOL_API_HOST || '127.0.0.1'}:${
  process.env.BTCS_POOL_API_PORT || 8765
}`
const apiProxy = new URL(process.env.API_PROXY ?? defaultApiProxy)
const contentTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml; charset=utf-8'],
  ['.png', 'image/png'],
  ['.ico', 'image/x-icon'],
])

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('PORT must be an integer between 1 and 65535')
}
if (apiProxy.protocol !== 'http:') {
  throw new Error('API_PROXY must be an http:// URL')
}

function proxyApi(request, response) {
  const target = new URL(request.url ?? '/', apiProxy)
  const headers = { ...request.headers, host: target.host }
  const upstream = httpRequest(
    target,
    {
      method: request.method,
      headers,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers)
      upstreamResponse.pipe(response)
    },
  )
  upstream.on('error', (error) => {
    if (!response.headersSent) {
      response.writeHead(502, {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
      })
    }
    response.end(
      JSON.stringify({
        ok: false,
        error: {
          code: 'api_proxy_unavailable',
          message: `The site could not reach the pool API at ${apiProxy.origin}: ${error.message}`,
        },
        meta: { timestamp: Date.now() / 1000 },
      }),
    )
  })
  request.pipe(upstream)
}

function isApiPath(pathname) {
  return pathname === '/api' || pathname.startsWith('/api/')
}

async function serveFile(request, response, pathname) {
  let relativePath = pathname.replace(/^\/+/, '')
  if (!relativePath) relativePath = 'index.html'
  if (relativePath.endsWith('/')) relativePath += 'index.html'

  let filePath = resolve(root, relativePath)
  if (filePath !== root && !filePath.startsWith(`${root}${sep}`)) {
    response.writeHead(403).end('Forbidden')
    return
  }

  try {
    let content = await readFile(filePath)
    // Route directories (/statistics/) map to their index document, and
    // extensionless clean URLs (/statistics) resolve the same way.
    try {
      await readFile(filePath)
    } catch (error) {
      if (error.code !== 'EISDIR') throw error
      filePath = resolve(filePath, 'index.html')
      content = await readFile(filePath)
    }
    response.writeHead(200, {
      'Content-Type': contentTypes.get(extname(filePath)) ?? 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'no-store',
    })
    response.end(request.method === 'HEAD' ? undefined : content)
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'EISDIR') {
      response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
      response.end('Not found')
      return
    }
    response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end('Server error')
  }
}

const server = createServer(async (request, response) => {
  if (request.method !== 'GET' && request.method !== 'HEAD' && request.method !== 'OPTIONS') {
    response.writeHead(405, { Allow: 'GET, HEAD, OPTIONS' }).end()
    return
  }

  let pathname
  try {
    pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname)
  } catch {
    response.writeHead(400).end('Bad request')
    return
  }

  if (isApiPath(pathname)) {
    proxyApi(request, response)
    return
  }

  if (request.method === 'OPTIONS') {
    response.writeHead(204, { Allow: 'GET, HEAD, OPTIONS' }).end()
    return
  }

  // Extensionless clean URLs resolve to a sibling index document. This keeps
  // /statistics and /statistics/ equivalent during development.
  const candidates = [pathname]
  if (!pathname.endsWith('/') && !extname(pathname)) {
    candidates.push(`${pathname}/index.html`)
    candidates.push(`${pathname}.html`)
  }
  for (const candidate of candidates) {
    const candidateRelative = candidate.replace(/^\/+/, '')
    const candidatePath = resolve(
      root,
      candidateRelative.endsWith('/') ? `${candidateRelative}index.html` : candidateRelative,
    )
    try {
      const stat = await readFile(candidatePath)
      if (stat) {
        await serveFile(request, response, candidate)
        return
      }
    } catch {
      // Try the next candidate.
    }
  }
  await serveFile(request, response, pathname)
})

server.listen(port, host, () => {
  process.stdout.write(
    `Silver Pool website: http://${host}:${port}/ (API proxy: ${apiProxy.origin})\n`,
  )
})
