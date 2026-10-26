import { projects } from './projects.mjs'

// API configuration - configurable base URL for deployed environments
// Can be overridden at runtime via window.API_BASE_URL before this module loads
// For Cloudflare Pages production, set window.API_BASE_URL to the full backend URL
// e.g., window.API_BASE_URL = 'https://your-domain.com/api'
const API_BASE_URL = (typeof window !== 'undefined' && window.API_BASE_URL) || '/api'

// Helper: show a loading state inside a container
function showLoading(containerId) {
  const container = document.getElementById(containerId)
  container.innerHTML = '<div class="loading-state"><p>Loading…</p></div>'
}

// Helper: show an error state inside a container
function showError(containerId, message) {
  const container = document.getElementById(containerId)
  container.innerHTML = '<div class="error-state">' +
    '<h3>Error Loading Data</h3>' +
    '<p>' + (message || 'Failed to load data. The pool backend may not be running.') + '</p>' +
    '<button class="button button-outline">Retry</button>' +
    '</div>'
}

// Helper: show an empty state inside a container
function showEmpty(containerId, message) {
  const container = document.getElementById(containerId)
  container.innerHTML = '<div class="empty-state">' +
    '<h3>No Data</h3>' +
    '<p>' + (message || 'No data available at this time.') + '</p>' +
    '</div>'
}

// Format a timestamp to a readable string
function formatTime(ts) {
  try { return new Date(ts * 1000).toLocaleString() } catch (e) { return String(ts) }
}

// Format satoshi to BTCS
function formatBTCS(satoshi) {
  if (satoshi == null) return '—'
  return (satoshi / 1e8).toFixed(8) + ' BTCS'
}

// Page routing configuration
const pageRoutes = {
  '/': 'overview',
  '/statistics': 'statistics',
  '/miners': 'miners',
  '/miner': 'miner',
  '/blocks': 'blocks',
  '/getting-started': 'getting-started',
  '/pool': 'pool',
  '/api-docs': 'api-docs',
  '/status': 'status',
  '/help': 'help'
}

// Page state tracking
const pageState = {
  currentPage: 'overview',
  hashrateHistory: [],
  workerHashrateHistory: [],
  shareHistory: [],
  activeWorkersHistory: [],
  blockHistory: [],
  timestamps: []
}

// Initialize the application
async function init() {
  const urlPath = window.location.pathname
  const route = Object.entries(pageRoutes).find(([path]) => {
    return urlPath === path || urlPath.endsWith(path)
  })
  const initialPage = route ? route[1] : 'overview'
  await showPage(initialPage)
  setupNavigation()
  await fetchPageData(initialPage)
  startPolling()
}

// Show a specific page by name
async function showPage(pageName) {
  hideAllPages()
  pageState.currentPage = pageName
  const container = document.getElementById('page-' + pageName)
  if (!container) {
    const fallback = document.getElementById('page-overview')
    if (fallback) fallback.classList.remove('hidden')
    return
  }
  container.classList.remove('hidden')
  updateActiveNav(pageName)
}

function hideAllPages() {
  document.querySelectorAll('[id^="page-"]').forEach(el => el.classList.add('hidden'))
}

function updateActiveNav(pageName) {
  document.querySelectorAll('.primary-navigation a, .nav-link').forEach(a => {
    a.classList.remove('active')
  })
  document.querySelectorAll('[data-page="' + pageName + '"]').forEach(a => {
    a.classList.add('active')
  })
}

// Fetch data for a specific page
async function fetchPageData(pageName) {
  switch (pageName) {
    case 'overview': await fetchOverviewData(); break
    case 'statistics': await fetchStatisticsData(); break
    case 'miners': await fetchMinersData(); break
    case 'miner': await fetchMinerDetailsData(); break
    case 'blocks': await fetchBlocksData(); break
    case 'pool': await fetchPoolData(); break
    case 'api-docs': setupApiDocsUI(); break
    case 'status': await fetchStatusData(); break
  }
}

// Fetch overview data
async function fetchOverviewData() {
  showLoading('page-overview')
  try {
    const response = await fetch(API_BASE_URL + '/pool/status')
    const data = await response.json()
    updateOverviewUI(data)
  } catch (error) {
    showError('page-overview', error.message)
  }
}

// Fetch statistics data
async function fetchStatisticsData() {
  showLoading('page-statistics')
  try {
    const [statsResp, historyResp] = await Promise.all([
      fetch(API_BASE_URL + '/pool/statistics'),
      fetch(API_BASE_URL + '/pool/history/hashrate?range=24h')
    ])
    const stats = await statsResp.json()
    const historyData = await historyResp.json()
    updateStatisticsUI(stats, historyData)
  } catch (error) {
    showError('page-statistics', error.message)
  }
}

// Fetch miners data
async function fetchMinersData() {
  showLoading('page-miners')
  try {
    const response = await fetch(API_BASE_URL + '/pool/miners')
    const data = await response.json()
    updateMinersUI(data.miners || [])
  } catch (error) {
    showError('page-miners', error.message)
  }
}

// Fetch miner details
async function fetchMinerDetailsData() {
  showLoading('page-miner')
  const urlParams = new URLSearchParams(window.location.search)
  const minerName = urlParams.get('miner') || ''
  if (!minerName) {
    showError('page-miner', 'No miner specified. Use ?miner=<name>')
    return
  }
  try {
    const [statusResp, sharesResp] = await Promise.all([
      fetch(API_BASE_URL + '/pool/miner/' + encodeURIComponent(minerName)),
      fetch(API_BASE_URL + '/pool/miner/' + encodeURIComponent(minerName) + '/shares')
    ])
    const minerData = await statusResp.json()
    const sharesData = await sharesResp.json()
    updateMinerDetailsUI(minerName, minerData, sharesData)
  } catch (error) {
    showError('page-miner', error.message)
  }
}

// Fetch blocks data
async function fetchBlocksData() {
  showLoading('page-blocks')
  try {
    const response = await fetch(API_BASE_URL + '/pool/blocks/recent')
    const data = await response.json()
    updateBlocksUI(data.blocks || [])
  } catch (error) {
    showError('page-blocks', error.message)
  }
}

// Fetch pool data
async function fetchPoolData() {
  showLoading('page-pool')
  try {
    const response = await fetch(API_BASE_URL + '/pool/statistics')
    const data = await response.json()
    updatePoolUI(data)
  } catch (error) {
    showError('page-pool', error.message)
  }
}

// Fetch status data
async function fetchStatusData() {
  showLoading('page-status')
  try {
    const [poolStatus, health] = await Promise.all([
      fetch(API_BASE_URL + '/pool/status').then(r => r.json()).catch(() => ({available: false})),
      fetch(API_BASE_URL + '/health').then(r => r.json()).catch(() => ({status: 'unknown'}))
    ])
    updateStatusUI(poolStatus, health)
  } catch (error) {
    showError('page-status', error.message)
  }
}

// --- UI Render Functions ---

function updateOverviewUI(data) {
  const container = document.getElementById('page-overview')
  const status = data.available ? 'online' : 'offline'
  let html = '<div class="overview-grid">' +
    '<div class="status-card ' + status + '">' +
    '<h3>Pool Status</h3>' +
    '<p>' + (data.available ? 'Online' : 'Offline') + '</p>' +
    '<p class="detail">' + (data.reason || '') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Miners</h3>' +
    '<p>' + (data.total_miners !== undefined ? data.total_miners : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Shares</h3>' +
    '<p>' + (data.total_shares !== undefined ? data.total_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Accepted Shares</h3>' +
    '<p>' + (data.accepted_shares !== undefined ? data.accepted_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Blocks</h3>' +
    '<p>' + (data.total_blocks !== undefined ? data.total_blocks : '—') + '</p>' +
    '</div>' +
    '</div>'
  if (data.recent_blocks && data.recent_blocks.length > 0) {
    html += '<div class="recent-blocks">' +
    '<h3>Recent Blocks</h3>' +
    '<table>' +
    '<thead><tr><th>Height</th><th>Hash</th><th>Status</th><th>Miner</th></tr></thead>' +
    '<tbody>' +
    data.recent_blocks.slice(0, 5).map(function(b) {
      return '<tr>' +
        '<td>' + b.height + '</td>' +
        '<td>' + (b.hash ? b.hash.substring(0, 16) + '…' : '—') + '</td>' +
        '<td>' + (b.status || '—') + '</td>' +
        '<td>' + (b.miner || '—') + '</td>' +
        '</tr>'
    }).join('') +
    '</tbody>' +
    '</table>' +
    '</div>'
  } else {
    html += '<div class="empty-state"><h3>No Blocks</h3><p>No blocks found yet.</p></div>'
  }
  container.innerHTML = html
}

function updateStatisticsUI(stats, historyData) {
  const container = document.getElementById('page-statistics')
  const history = historyData.history || []
  let html = '<div class="statistics-grid">' +
    '<div class="stat-card">' +
    '<h3>Total Miners</h3>' +
    '<p>' + (stats.total_miners !== undefined ? stats.total_miners : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Shares</h3>' +
    '<p>' + (stats.total_shares !== undefined ? stats.total_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Accepted Shares</h3>' +
    '<p>' + (stats.accepted_shares !== undefined ? stats.accepted_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Blocks</h3>' +
    '<p>' + (stats.total_blocks !== undefined ? stats.total_blocks : '—') + '</p>' +
    '</div>' +
    '</div>'
  if (history.length > 0) {
    const labels = history.map(function(h) {
      return new Date(h.timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
    })
    const values = history.map(function(h) { return h.hashrate || 0 })
    html += '<div class="chart-container">' +
    '<h3>Hashrate History (24h)</h3>' +
    '<canvas id="hashrateChart" width="600" height="300"></canvas>' +
    '</div>' +
    '<script>' +
    'var ctx = document.getElementById("hashrateChart");' +
    'if (ctx && window.Chart) {' +
    '  new Chart(ctx.getContext("2d"), {' +
    '    type: "line",' +
    '    data: {labels: ' + JSON.stringify(labels) + ', datasets: [{label: "Hashrate", data: ' + JSON.stringify(values) + ', borderColor: "#1677d2", fill: false}]},' +
    '    options: {responsive: true, scales: {y: {beginAtZero: true}}}' +
    '  });' +
    '}' +
    '</script>'
  } else {
    html += '<div class="empty-state"><h3>No Hashrate Data</h3><p>No historical hashrate data available yet.</p></div>'
  }
  container.innerHTML = html
}

function updateMinersUI(miners) {
  const container = document.getElementById('page-miners')
  if (miners.length === 0) {
    container.innerHTML = '<div class="empty-state"><h3>No Miners</h3><p>No miners registered yet.</p></div>'
    return
  }
  let html = '<div class="miners-list">' +
    '<table>' +
    '<thead><tr><th>Miner</th><th>Shares</th><th>Status</th></tr></thead>' +
    '<tbody>' +
    miners.map(function(m) {
      return '<tr>' +
        '<td><a href="/miner?miner=' + encodeURIComponent(m) + '">' + m + '</a></td>' +
        '<td>—</td>' +
        '<td><span class="status-dot status-active"></span> Active</td>' +
        '</tr>'
    }).join('') +
    '</tbody>' +
    '</table>' +
    '</div>'
  container.innerHTML = html
}

function updateMinerDetailsUI(minerName, minerData, sharesData) {
  const container = document.getElementById('page-miner')
  var available = minerData.available !== false
  var shares = sharesData.shares || []
  let html = '<div class="miner-details">' +
    '<h2>Miner: ' + minerName + '</h2>' +
    '<div class="miner-status">' +
    '<p><strong>Status:</strong> ' + (available ? 'Active' : 'Not found') + '</p>' +
    '<p><strong>Available:</strong> ' + (minerData.available_satoshi !== undefined ? formatBTCS(parseFloat(minerData.available_satoshi)) : '—') + '</p>' +
    '<p><strong>Immature:</strong> ' + (minerData.immature_satoshi !== undefined ? formatBTCS(parseFloat(minerData.immature_satoshi)) : '—') + '</p>' +
    '<p><strong>Total:</strong> ' + (minerData.total_satoshi !== undefined ? formatBTCS(parseFloat(minerData.total_satoshi)) : '—') + '</p>' +
    '</div>'
  if (shares.length > 0) {
    html += '<div class="miner-shares">' +
    '<h3>Recent Shares</h3>' +
    '<table>' +
    '<thead><tr><th>Job ID</th><th>Nonce</th><th>Accepted</th><th>Difficulty</th><th>Time</th></tr></thead>' +
    '<tbody>' +
    shares.map(function(s) {
      return '<tr>' +
        '<td>' + s.job_id + '</td>' +
        '<td>' + s.nonce + '</td>' +
        '<td><span class="status-dot ' + (s.accepted ? 'status-active' : 'status-rejected') + '"></span> ' + (s.accepted ? 'Yes' : 'No') + '</td>' +
        '<td>' + s.difficulty + '</td>' +
        '<td>' + formatTime(s.created_at) + '</td>' +
        '</tr>'
    }).join('') +
    '</tbody>' +
    '</table>' +
    '</div>'
  } else {
    html += '<div class="empty-state"><h3>No Shares</h3><p>No shares recorded for this miner.</p></div>'
  }
  html += '</div>'
  container.innerHTML = html
}

function updateBlocksUI(blocks) {
  const container = document.getElementById('page-blocks')
  if (blocks.length === 0) {
    container.innerHTML = '<div class="empty-state"><h3>No Blocks</h3><p>No blocks found yet.</p></div>'
    return
  }
  let html = '<div class="blocks-list">' +
    '<table>' +
    '<thead><tr><th>Height</th><th>Hash</th><th>Status</th><th>Reward</th><th>Miner</th></tr></thead>' +
    '<tbody>' +
    blocks.map(function(b) {
      return '<tr>' +
        '<td>' + b.height + '</td>' +
        '<td>' + (b.hash ? b.hash : '—') + '</td>' +
        '<td>' + (b.status || '—') + '</td>' +
        '<td>' + formatBTCS(b.net_reward || 0) + '</td>' +
        '<td>' + (b.miner || '—') + '</td>' +
        '</tr>'
    }).join('') +
    '</tbody>' +
    '</table>' +
    '</div>'
  container.innerHTML = html
}

function updatePoolUI(data) {
  const container = document.getElementById('page-pool')
  let html = '<div class="pool-info">' +
    '<h2>Pool Information</h2>' +
    '<div class="stat-card">' +
    '<h3>Total Miners</h3>' +
    '<p>' + (data.total_miners !== undefined ? data.total_miners : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Shares</h3>' +
    '<p>' + (data.total_shares !== undefined ? data.total_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Accepted Shares</h3>' +
    '<p>' + (data.accepted_shares !== undefined ? data.accepted_shares : '—') + '</p>' +
    '</div>' +
    '<div class="stat-card">' +
    '<h3>Total Blocks</h3>' +
    '<p>' + (data.total_blocks !== undefined ? data.total_blocks : '—') + '</p>' +
    '</div>' +
    '<div class="info-card">' +
    '<h3>Fee Configuration</h3>' +
    '<p>Pool fee: 2.00% (configurable 0.00% – 5.00%)</p>' +
    '<p>Minimum payout: 0.01 BTCS</p>' +
    '<p>Payout interval: 300 seconds</p>' +
    '<p>Automatic payouts: disabled</p>' +
    '</div>' +
    '</div>'
  container.innerHTML = html
}

function updateStatusUI(poolStatus, health) {
  const container = document.getElementById('page-status')
  var dbHealthy = health.database !== false
  let html = '<div class="health-grid">' +
    '<div class="health-card ' + (poolStatus.available ? 'healthy' : 'unhealthy') + '">' +
    '<h3>Pool API</h3>' +
    '<p>' + (poolStatus.available ? 'Operational' : 'Unavailable') + '</p>' +
    '<p class="detail">' + (poolStatus.reason || '') + '</p>' +
    '</div>' +
    '<div class="health-card ' + (dbHealthy ? 'healthy' : 'unhealthy') + '">' +
    '<h3>Database</h3>' +
    '<p>' + (dbHealthy ? 'Connected' : 'Not found') + '</p>' +
    '</div>' +
    '<div class="health-card healthy">' +
    '<h3>Frontend</h3>' +
    '<p>Operational</p>' +
    '</div>' +
    '</div>'
  if (poolStatus.available && poolStatus.database_healthy !== undefined) {
    html += '<div class="status-details">' +
    '<h3>Pool Details</h3>' +
    '<p>Miners: ' + poolStatus.total_miners + '</p>' +
    '<p>Shares: ' + poolStatus.total_shares + '</p>' +
    '<p>Blocks: ' + poolStatus.total_blocks + '</p>' +
    '</div>'
  }
  container.innerHTML = html
}

// Setup navigation
function setupNavigation() {
  document.querySelectorAll('a[data-page], .primary-navigation a').forEach(function(a) {
    a.addEventListener('click', function(e) {
      var href = a.getAttribute('href')
      if (href.startsWith('#')) return
      if (href.startsWith('/') || href === './' || href === '.') {
        e.preventDefault()
        var path = href === './' || href === '.' ? '/' : href
        window.history.pushState({}, '', path)
        var route = Object.entries(pageRoutes).find(function(p) { return path === p[0] || path.endsWith(p[0]) })
        var page = route ? route[1] : 'overview'
        showPage(page)
        fetchPageData(page)
      }
    })
  })
  window.addEventListener('popstate', function() {
    var urlPath = window.location.pathname
    var route = Object.entries(pageRoutes).find(function(p) { return urlPath === p[0] || urlPath.endsWith(p[0]) })
    var page = route ? route[1] : 'overview'
    showPage(page)
    fetchPageData(page)
  })
}

// Start polling
function startPolling() {
  setInterval(function() { fetchPageData(pageState.currentPage) }, 30000)
}

// Initialize application on DOM load
document.addEventListener('DOMContentLoaded', function() { init() })
