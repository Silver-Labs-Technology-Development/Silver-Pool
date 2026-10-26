import {
  API_BASE,
  apiGet,
  clear,
  el,
  formatNumber,
  initCopyButtons,
  initLayout,
  setState,
  setText,
} from './site.js'

initLayout()

const stateBox = document.getElementById('api-state')
const body = document.getElementById('api-endpoints-body')
const apiRoot = new URL(`${API_BASE.replace(/\/+$/, '')}/`, window.location.origin)
const apiBaseDisplay = apiRoot.href.replace(/\/$/, '')

function render(endpoints, docs) {
  clear(body)
  if (!endpoints.length) {
    const tr = el('tr')
    const td = el('td', 'table-empty', 'The API did not return any endpoints.')
    td.colSpan = 3
    tr.append(td)
    body.append(tr)
    return
  }
  for (const endpoint of endpoints) {
    const tr = el('tr')
    tr.append(el('td', 'mono', endpoint.method))
    tr.append(el('td', 'mono', endpoint.path))
    tr.append(el('td', null, endpoint.description || '—'))
    body.append(tr)
  }
  setText('api-base', apiBaseDisplay)
  setText('api-auth', docs.authentication === 'none' ? 'None (public read-only)' : docs.authentication)
  setText('api-rate', `${formatNumber(docs.rate_limit_per_minute)} requests/minute per client`)
  setText('api-endpoint-count', `${formatNumber(endpoints.length)} endpoints served by this API.`)
  setText('curl-example', `curl -sS ${apiBaseDisplay}/health`)
  const openapi = document.getElementById('openapi-link')
  openapi.href = `${apiBaseDisplay}/openapi.json`
  openapi.textContent = 'OpenAPI 3.0 document'
  setState(stateBox, 'ok', 'API index loaded', 'This index was returned by the running backend at /api/docs.')
  initCopyButtons()
}

async function load() {
  setState(stateBox, 'loading', 'Loading API index', 'Reading the running API documentation…')
  try {
    const docs = await apiGet('/docs')
    setText('api-base', apiBaseDisplay)
    setText('api-rate', `${formatNumber(docs.rate_limit_per_minute)} requests/minute per client`)
    render(docs.endpoints || [], docs)
  } catch (error) {
    clear(body)
    const tr = el('tr')
    const td = el('td', 'table-empty', 'API endpoint index unavailable.')
    td.colSpan = 3
    tr.append(td)
    body.append(tr)
    setText('api-endpoint-count', 'API unavailable')
    setState(stateBox, 'error', 'API documentation unavailable', `${error.message} The live endpoint index is not being replaced with guessed routes.`)
  }
}

load()
