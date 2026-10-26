const runtimeBase =
  typeof window !== 'undefined' && window.SILVER_POOL_CONFIG
    ? window.SILVER_POOL_CONFIG.apiBaseUrl
    : ''
const buildBase = import.meta.env?.VITE_API_BASE_URL ?? ''
export const API_BASE = (runtimeBase || buildBase || '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'network_error', details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export async function apiRequest(path, { timeoutMs = 12000, signal } = {}) {
  const url = `${API_BASE}${path}`
  let timer
  let controller
  let requestSignal = signal
  if (!requestSignal && typeof AbortController !== 'undefined') {
    controller = new AbortController()
    requestSignal = controller.signal
    timer = setTimeout(() => controller.abort(), timeoutMs)
  }
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: requestSignal,
    })
    let body = null
    try {
      body = await response.json()
    } catch {
      throw new ApiError('The API returned a non-JSON response.', {
        status: response.status,
        code: 'invalid_response',
      })
    }
    return {
      ok: response.ok && body?.ok === true,
      status: response.status,
      body,
      data: body?.data ?? null,
      error: body?.error ?? null,
    }
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error?.name === 'AbortError') {
      throw new ApiError('The API request timed out.', { code: 'timeout' })
    }
    throw new ApiError('The pool API is unreachable.', {
      code: 'network_error',
      details: error,
    })
  } finally {
    clearTimeout(timer)
  }
}

export async function apiGet(path, options) {
  const response = await apiRequest(path, options)
  if (!response.ok) {
    throw new ApiError(
      response.error?.message || `API request failed with HTTP ${response.status}.`,
      {
        status: response.status,
        code: response.error?.code || 'api_error',
        details: response.error?.details ?? null,
      },
    )
  }
  return response.data
}

export function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined && text !== null) node.textContent = String(text)
  return node
}

export function clear(node) {
  if (!node) return
  while (node.firstChild) node.removeChild(node.firstChild)
}

export function setText(id, value) {
  const node = typeof id === 'string' ? document.getElementById(id) : id
  if (node) node.textContent = value === undefined || value === null ? '—' : String(value)
}

export function setState(container, kind, title, message) {
  if (!container) return
  clear(container)
  const panel = el('div', `state-panel state-${kind}`)
  panel.append(el('h3', null, title))
  if (message) panel.append(el('p', null, message))
  container.append(panel)
}

export function formatNumber(value, maximumFractionDigits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits }).format(Number(value))
}

export function formatHashrate(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return { value: '0', unit: 'H/s' }
  const units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s']
  let scaled = number
  let index = 0
  while (scaled >= 1000 && index < units.length - 1) {
    scaled /= 1000
    index += 1
  }
  const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2
  return {
    value: new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(scaled),
    unit: units[index],
  }
}

export function formatBtcS(satoshis) {
  const number = Number(satoshis)
  if (!Number.isFinite(number)) return '—'
  return `${(number / 1e8).toFixed(8)} BTCS`
}

export function formatTime(timestamp) {
  if (timestamp === null || timestamp === undefined) return '—'
  const date = new Date(Number(timestamp) * 1000)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date)
}

export function timeAgo(timestamp) {
  if (!timestamp) return '—'
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(timestamp)))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function shortHash(hash, size = 12) {
  if (!hash) return '—'
  return hash.length <= size * 2 ? hash : `${hash.slice(0, size)}…${hash.slice(-size)}`
}

export function statusBadge(status) {
  const badge = el('span', `badge badge-${status}`, status)
  return badge
}

export function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.append(area)
  area.select()
  document.execCommand('copy')
  area.remove()
  return Promise.resolve()
}

export function initLayout() {
  const toggle = document.querySelector('[data-menu-toggle]')
  const nav = document.querySelector('[data-nav]')
  if (toggle && nav) {
    const close = () => {
      nav.classList.remove('is-open')
      toggle.setAttribute('aria-expanded', 'false')
    }
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('is-open')
      toggle.setAttribute('aria-expanded', String(open))
    })
    nav.addEventListener('click', (event) => {
      if (event.target.closest('a')) close()
    })
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') close()
    })
  }
  const page = document.body.dataset.page
  if (page) {
    document.querySelectorAll('[data-page]').forEach((link) => {
      if (link.dataset.page === page) {
        link.classList.add('is-active')
        link.setAttribute('aria-current', 'page')
      }
    })
  }
}

export function initCopyButtons() {
  document.querySelectorAll('[data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copyTarget)
      if (!target) return
      const text = target.textContent || ''
      try {
        await copyText(text)
        const original = button.textContent
        button.textContent = 'Copied'
        setTimeout(() => {
          button.textContent = original
        }, 1400)
      } catch {
        button.textContent = 'Copy failed'
      }
    })
  })
}

export function startPolling(callback, intervalMs = 15000) {
  let timer = null
  let running = false
  const run = async () => {
    if (running || document.hidden) return
    running = true
    try {
      await callback()
    } finally {
      running = false
    }
  }
  const start = () => {
    stop()
    timer = setInterval(run, intervalMs)
  }
  const stop = () => {
    if (timer) clearInterval(timer)
    timer = null
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop()
    else {
      run()
      start()
    }
  })
  start()
  return { run, stop }
}

export function markUpdated(id = 'last-updated') {
  setText(id, `Updated ${new Date().toLocaleTimeString()}`)
}
