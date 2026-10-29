// This module is bundled into the Worker, never the public static asset folder.
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]))

export function renderAdmin(email) {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>Private administration — Silver Pool</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101315;color:#f4f1e8}*{box-sizing:border-box}body{margin:0}header,main,footer{max-width:1040px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;gap:24px;border-bottom:1px solid #394045}a{color:#e4c778}nav{display:flex;gap:20px;flex-wrap:wrap}h1{font-size:clamp(2rem,5vw,3.5rem);line-height:1.1}p{line-height:1.6;color:#c1c7c6}.eyebrow{color:#e4c778;letter-spacing:.12em;font-size:.8rem}.notice,.panel{border:1px solid #394045;border-radius:12px;padding:24px;margin:24px 0}.notice{border-color:#e4c778}.rows{display:grid;grid-template-columns:1fr 1fr;gap:16px}dt{color:#b1b9b8}dd{margin:4px 0 0;font-weight:600}.identity{overflow-wrap:anywhere}footer{font-size:.9rem}@media(max-width:560px){header{flex-direction:column}.rows{grid-template-columns:1fr}}
</style></head><body>
<header><strong>SILVER POOL · PRIVATE PORTAL</strong><nav aria-label="Private navigation"><a href="/admin/" aria-current="page">Admin</a><a href="/">Public site</a><a href="/cdn-cgi/access/logout">Sign out</a></nav></header>
<main><p class="eyebrow">VERIFIED OWNER ACCESS</p><h1>Administration</h1><p class="identity">Signed in as ${escapeHtml(email)}.</p>
<section class="notice" aria-label="Test mode"><h2>Test mode</h2><p>This is a read-only access foundation. The local backend is not connected to this portal. No private node, wallet or miner data is loaded.</p></section>
<section class="panel"><h2>Current safeguards</h2><dl class="rows"><div><dt>Access</dt><dd>Verified owner only</dd></div><div><dt>Administration</dt><dd>Read only</dd></div><div><dt>Automatic payouts</dt><dd>Disabled</dd></div><div><dt>Node and wallet controls</dt><dd>Unavailable</dd></div></dl><p>Public pages do not include an Admin tab. Every private page and private API request must pass the server-side identity check.</p></section>
<section class="panel"><h2>Before a live launch</h2><p>Connect and verify the local services, coin networks, share accounting, backups and payout process separately. Installing a coin node does not create mining revenue.</p></section>
</main><footer>Private test environment · No fund transfers or server changes are available here.</footer></body></html>`
}
