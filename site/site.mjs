import { projects } from './projects.mjs'

// Initialize the application
async function init() {
  // Parse current page from URL path
  const urlPath = window.location.pathname
  const route = Object.entries(pageRoutes).find(([path]) => {
    return urlPath === path || urlPath.endsWith(path)
  })
  const initialPage = route ? route[1] : 'overview'

  // Show the initial page
  await showPage(initialPage)

  // Set up navigation
  setupNavigation()

  // Fetch data and start polling
  await fetchPageData(initialPage)
  startPolling()
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

// API configuration - configurable base URL for deployed environments
//
const API_BASE_URL = "/api"
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
  try {
    const response = await fetch(API_BASE_URL + '/pool/status')
    if (!response.ok) throw new Error('Failed')
    const data = await response.json()
    updateStatusGrid(data)
  } catch (error) { showErrorState('overview') }
}

// Fetch statistics data
async function fetchStatisticsData() {
  try {
    const statusResponse = await fetch(API_BASE_URL + '/pool/statistics')
    const stats = await statusResponse.json()
    const historyResponse = await fetch(API_BASE_URL + '/pool/history/hashrate?range=24h')
    const historyData = await historyResponse.json()
    updateStatisticsUI(stats, historyData)
  } catch (error) { showErrorState('statistics') }
}

// Fetch miners data
async function fetchMinersData() {
  try {
    const response = await fetch(API_BASE_URL + '/pool/miners')
    const data = await response.json()
    updateMinersUI(data.miners || [])
  } catch (error) { showErrorState('miners') }
}

// Fetch miner details
async function fetchMinerDetailsData() {
  const urlParams = new URLSearchParams(window.location.search)
  const minerName = urlParams.get('miner') || 'miner1'
  try {
    const response = await fetch(API_BASE_URL + '/pool/miner/' + minerName)
    const data = await response.json()
    updateMinerDetailsUI(data)
  } catch (error) { showErrorState('miner') }
}

// Fetch blocks data
async function fetchBlocksData() {
  try {
    const response = await fetch(API_BASE_URL + '/pool/blocks/recent')
    const data = await response.json()
    updateBlocksUI(data.blocks || [])
  } catch (error) { showErrorState('blocks') }
}

// Fetch pool data
async function fetchPoolData() {
  try {
    const response = await fetch(API_BASE_URL + '/pool/statistics')
    const data = await response.json()
    updatePoolUI(data)
  } catch (error) { console.error(error) }
}

// Setup API docs UI
function setupApiDocsUI() {
  const container = document.querySelector('.api-docs-content')
  if (!container) return
  container.innerHTML = '<h3>API Endpoints</h3>' +
    '<table>' +
      '<thead>' +
        '<tr>' +
          '<th>Endpoint</th>' +
          '<th>Method</th>' +
          '<th>Description</th>' +
        '</tr>' +
      '</thead>' +
      '<tbody>' +
        '<tr><td>/api/pool/status</td><td>GET</td><td>Return pool status</td></tr>' +
        '<tr><td>/api/pool/miner/{username}</td><td>GET</td><td>Return miner status</td></tr>' +
        '<tr><td>/api/pool/miners</td><td>GET</td><td>List all registered miners</td></tr>' +
        '<tr><td>/api/pool/shares/recent</td><td>GET</td><td>Return recent shares</td></tr>' +
        '<tr><td>/api/pool/blocks/recent</td><td>GET</td><td>Return recent blocks</td></tr>' +
        '<tr><td>/api/pool/fee-ledger</td><td>GET</td><td>Return fee ledger</td></tr>' +
        '<tr><td>/api/pool/statistics</td><td>GET</td><td>Return pool statistics</td></tr>' +
        '<tr><td>/api/health</td><td>GET</td><td>Return health check</td></tr>' +
      '</tbody>' +
    '</table>' +
    '<p><strong>Base URL:</strong> <code>/api</code>. Configure <code>API_BASE_URL</code> for deployed environments.</p>'
}

// Fetch status data
async function fetchStatusData() {
  try {
    const [poolStatus, health] = await Promise.all([
      fetch(API_BASE_URL + '/pool/status').then(r => r.json()).catch(() => ({})),
      fetch(API_BASE_URL + '/health').then(r => r.json()).catch(() => ({}))
    ])
    updateStatusUI(poolStatus, health)
  } catch (error) { showErrorState('status') }
}

// Show error state
function showErrorState(pageName) {
  hideAllPages()
  const container = document.getElementById('page-' + pageName)
  if (container) {
    container.classList.remove('hidden')
    container.innerHTML = '<div class="error-state">' +
      '<h3>Error Loading Data</h3>' +
      '<p>Failed to load data. The pool backend may not be running.</p>' +
      '<button class="button button-outline" onclick="fetchPageData(\'' + pageName + '\')">Retry</button>' +
      '</div>'
  }
}

// Start polling
function startPolling() {
  setInterval(async () => { await fetchPageData(pageState.currentPage) }, 30000)
}

// Initialize application on DOM load
document.addEventListener('DOMContentLoaded', () => { init() })
