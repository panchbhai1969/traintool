const state = {
  dataset: null,
  query: '',
  imageIndex: 0,
  selected: new Set(),
  results: {},
  enhanced: {},
  activeCrop: null,
  finding: 'stain',
  prompts: {},
  prompt: '',
  promptDirty: false,
  promptSaveStatus: 'Saved',
  schemaText: '',
  model: '',
  maxTokens: 800,
  maxEdge: 896,
  padding: .25,
  mode: 'parallel',
  concurrency: 8,
  running: false,
  uploading: false,
  banner: '',
  controller: null,
  history: [],
  historyOpen: false,
  activeHistory: null,
  configOpen: false,
  leftPanelOpen: false,
}

const root = document.querySelector('#root')

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character])
}

function findingLabel(finding = state.finding) {
  return finding.charAt(0).toUpperCase() + finding.slice(1)
}

function resultVerdict(event) {
  if (event?.type !== 'completed') return null
  return ['present', 'absent'].includes(event.result?.verdict) ? event.result.verdict : null
}

function images() {
  if (!state.dataset) return []
  const query = state.query.trim().toLowerCase()
  return query ? state.dataset.images.filter(image => image.image_id.toLowerCase().includes(query)) : state.dataset.images
}

function currentImage() {
  const available = images()
  return available[Math.min(state.imageIndex, Math.max(0, available.length - 1))]
}

function paddedBox(crop) {
  const extraX = crop.box.width * state.padding
  const extraY = crop.box.height * state.padding
  const x = Math.max(0, crop.box.x - extraX)
  const y = Math.max(0, crop.box.y - extraY)
  return { x, y, width: Math.min(100 - x, crop.box.width + extraX * 2), height: Math.min(100 - y, crop.box.height + extraY * 2) }
}

function cropSvg(image, crop) {
  const box = paddedBox(crop)
  const x = box.x * crop.original_width / 100
  const y = box.y * crop.original_height / 100
  const width = box.width * crop.original_width / 100
  const height = box.height * crop.original_height / 100
  return `<svg class="crop-image" viewBox="${x} ${y} ${width} ${height}" role="img" aria-label="Tooth crop"><rect width="${crop.original_width}" height="${crop.original_height}" fill="#777"/><image href="${escapeHtml(image.image_url)}" width="${crop.original_width}" height="${crop.original_height}" preserveAspectRatio="none"/></svg>`
}

function cropVisual(image, crop) {
  const enhanced = state.enhanced[crop.crop_id]
  if (enhanced?.status === 'ready' && enhanced.shown) {
    return `<img class="crop-image" src="${enhanced.image}" alt="Enhanced tooth crop" />`
  }
  return cropSvg(image, crop)
}

function enhanceLabel(enhanced) {
  if (enhanced?.status === 'loading') return 'Enhancing…'
  if (enhanced?.status === 'failed') return 'Retry enhance'
  if (enhanced?.status === 'ready') return enhanced.shown ? 'Show original' : 'Show enhanced'
  return '✨ Enhance'
}

function resultClass(event) {
  if (!event) return ''
  if (resultVerdict(event) === 'present') return 'positive'
  if (resultVerdict(event) === 'absent') return 'negative'
  if (event.type === 'failed' || event.type === 'parse_error') return 'errored'
  if (['running', 'queued', 'rate_limited'].includes(event.type)) return 'working'
  return ''
}

function cropCards(image) {
  if (!image.crops.length) return '<div class="no-crops"><h3>No tooth boxes detected</h3><p class="muted">The source image is shown below.</p></div>'
  return `<div class="crop-grid">${image.crops.map((crop, index) => {
    const event = state.results[crop.crop_id]
    const enhanced = state.enhanced[crop.crop_id]
    const verdict = resultVerdict(event)
    return `<article class="crop-card ${state.selected.has(crop.crop_id) ? 'selected' : ''} ${resultClass(event)}" data-crop="${escapeHtml(crop.crop_id)}">
      <div class="crop-frame">${cropVisual(image, crop)}</div>
      <div class="crop-meta"><span>Tooth ${index + 1}</span><span class="status">${escapeHtml(event?.type?.replace('_', ' ') || 'ready')}</span></div>
      <div class="crop-actions"><button class="enhance-btn ${enhanced?.status || ''}" data-enhance="${escapeHtml(crop.crop_id)}" ${enhanced?.status === 'loading' ? 'disabled' : ''}>${enhanceLabel(enhanced)}</button></div>
      ${verdict ? `<div class="verdict"><b>${verdict === 'present' ? `${findingLabel()} present` : `No ${state.finding}`}</b></div>` : ''}
    </article>`
  }).join('')}</div>`
}

function detectionClass(crop) {
  const verdict = resultVerdict(state.results[crop.crop_id])
  if (verdict === 'present') return 'finding-present'
  if (verdict === 'absent') return 'finding-absent'
  return 'undecided'
}

function sourceOverview(image) {
  const boxes = image.crops.map((crop, index) => `<button
    class="detection-box ${detectionClass(crop)} ${state.selected.has(crop.crop_id) ? 'selected' : ''}"
    data-overview-crop="${escapeHtml(crop.crop_id)}"
    style="left:${crop.box.x}%;top:${crop.box.y}%;width:${crop.box.width}%;height:${crop.box.height}%"
    aria-label="Select tooth ${index + 1}"
    title="Tooth ${index + 1}"
  ><span>${index + 1}</span></button>`).join('')
  return `<section class="source-overview">
    <div class="source-overview-heading"><div><p class="eyebrow">Full source image</p><h3>${findingLabel()} detection overview</h3></div><div class="detection-legend"><span class="finding-present">Present</span><span class="finding-absent">Absent</span><span class="undecided">Not decided</span></div></div>
    <div class="annotated-source"><img src="${escapeHtml(image.image_url)}" alt="Full dental source image"/>${boxes}</div>
  </section>`
}

function detail(image) {
  const crop = image.crops.find(item => item.crop_id === state.activeCrop)
  if (!crop) return ''
  const event = state.results[crop.crop_id]
  const result = event?.result
  const orderedResult = result?.reasoning === undefined ? result : { reasoning: result.reasoning, ...Object.fromEntries(Object.entries(result).filter(([key]) => key !== 'reasoning')) }
  const body = event ? JSON.stringify(orderedResult || { error: event.error, raw: event.raw }, null, 2) : ''
  const explanation = result?.reasoning == null ? '' : `<div class="explanation"><span>Explanation</span><p>${escapeHtml(result.reasoning)}</p></div>`
  const decided = resultVerdict(event)
  const verdict = decided ? `<div class="detail-verdict"><span>Verdict</span><b>${decided === 'present' ? `${findingLabel()} present` : `No ${state.finding}`}</b></div>` : ''
  return `<section class="detail"><div class="detail-image">${cropVisual(image, crop)}</div><div>
    <p class="eyebrow">Selected tooth</p><h3>${escapeHtml(crop.crop_id)}</h3>
    ${event ? `${explanation}${verdict}<div class="metrics"><span>${event.latency_ms ? `${event.latency_ms} ms` : '—'}</span><span>${event.prompt_tokens ?? '—'} prompt tokens</span><span>${event.completion_tokens ?? '—'} completion tokens</span><span>${event.cost != null ? `$${event.cost}` : 'cost unavailable'}</span></div><pre>${escapeHtml(body)}</pre>` : '<p class="muted">Run this crop to inspect its structured response.</p>'}
  </div></section>`
}

function formatCost(entry) {
  const amount = `$${entry.cost.toFixed(6)}`
  if (entry.missingCost === entry.calls) return `Unavailable · ${entry.missingCost} call${entry.missingCost === 1 ? '' : 's'}`
  return entry.missingCost ? `${amount} · ${entry.missingCost} unavailable` : amount
}

function historyTime(entry) {
  return escapeHtml(new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
}

function evalHistoryRow(entry) {
  return `<tr>
    <td>${historyTime(entry)}</td>
    <td class="history-image">${escapeHtml(entry.imageId)}</td>
    <td><b class="history-finding">${escapeHtml(findingLabel(entry.finding))}</b><span class="history-model">${escapeHtml(entry.model)}</span><small>${escapeHtml(entry.mode)}${entry.mode === 'parallel' ? ` · ${entry.concurrency} workers` : ''}</small></td>
    <td><b>${entry.calls}</b></td>
    <td><span class="history-ok">${entry.completed} completed</span>${entry.parseErrors ? `<span class="history-warn">${entry.parseErrors} parse errors</span>` : ''}${entry.failed ? `<span class="history-bad">${entry.failed} failed</span>` : ''}${entry.cancelled ? `<span class="history-muted">${entry.cancelled} cancelled</span>` : ''}</td>
    <td class="history-cost">${escapeHtml(formatCost(entry))}</td>
    <td><span class="history-status ${entry.status}">${escapeHtml(entry.status)}</span></td>
  </tr>`
}

function enhanceHistoryRow(entry) {
  const meta = [
    entry.latencyMs != null ? `${(entry.latencyMs / 1000).toFixed(1)}s` : '',
    entry.imageTokens != null ? `${entry.imageTokens} image tokens` : '',
  ].filter(Boolean).join(' · ')
  return `<tr>
    <td>${historyTime(entry)}</td>
    <td class="history-image" title="${escapeHtml(entry.cropId)}">${escapeHtml(entry.imageId)}</td>
    <td><b class="history-finding">Enhance</b><span class="history-model">${escapeHtml(entry.model || '—')}</span><small>${escapeHtml(meta)}</small></td>
    <td><b>1</b></td>
    <td>${entry.completed ? '<span class="history-ok">1 enhanced</span>' : `<span class="history-bad">1 failed</span>`}</td>
    <td class="history-cost">${escapeHtml(formatCost(entry))}</td>
    <td><span class="history-status ${entry.status}">${escapeHtml(entry.status)}</span></td>
  </tr>`
}

function historyRows() {
  if (!state.history.length) return '<div class="history-empty">No runs in this session yet.</div>'
  return `<div class="history-table-wrap"><table class="history-table">
    <thead><tr><th>Time</th><th>Image ID</th><th>Task / model / execution</th><th>Calls</th><th>Results</th><th>Total cost</th><th>Status</th></tr></thead>
    <tbody>${state.history.map(entry => entry.kind === 'enhance' ? enhanceHistoryRow(entry) : evalHistoryRow(entry)).join('')}</tbody>
  </table></div>`
}

function historyDialog() {
  return `<dialog id="historyDialog" class="history-dialog">
    <div class="history-heading"><div><p class="eyebrow">Current browser session</p><h2>Run history</h2><p class="muted">Costs are summed from OpenRouter's per-call usage details.</p></div><button id="closeHistory" class="dialog-close" aria-label="Close">×</button></div>
    ${historyRows()}
    <div class="history-footer"><span>${state.history.length} ${state.history.length === 1 ? 'entry' : 'entries'}</span><button id="clearHistory" ${state.history.length ? '' : 'disabled'}>Clear history</button></div>
  </dialog>`
}

function imageIdForCrop(cropId) {
  for (const image of state.dataset.images) {
    if (image.crops.some(crop => crop.crop_id === cropId)) return image.image_id
  }
  return 'unknown'
}

function recordEnhanceHistory(cropId, { ok, body = {}, clientMs, error } = {}) {
  const usage = body.usage || {}
  const cost = Number(usage.cost)
  const hasCost = ok && usage.cost != null && Number.isFinite(cost)
  state.history.unshift({
    id: `enhance:${cropId}:${Date.now()}`,
    kind: 'enhance',
    timestamp: new Date().toISOString(),
    imageId: imageIdForCrop(cropId),
    cropId,
    model: body.model || '',
    latencyMs: body.latency_ms ?? clientMs ?? null,
    imageTokens: usage.image_tokens ?? usage.completion_tokens ?? null,
    calls: 1,
    completed: ok ? 1 : 0,
    parseErrors: 0,
    failed: ok ? 0 : 1,
    cancelled: 0,
    cost: hasCost ? cost : 0,
    missingCost: hasCost ? 0 : 1,
    status: ok ? 'completed' : 'failed',
    error: error || null,
  })
}

function beginHistory(cropIds) {
  const runId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  const timestamp = new Date().toISOString()
  const grouped = new Map()
  cropIds.forEach(cropId => {
    const imageId = imageIdForCrop(cropId)
    if (!grouped.has(imageId)) grouped.set(imageId, [])
    grouped.get(imageId).push(cropId)
  })
  const cropEntries = new Map()
  const entries = []
  for (const [imageId, ids] of grouped) {
    const entry = {
      id: `${runId}:${imageId}`,
      runId,
      imageId,
      timestamp,
      finding: state.finding,
      model: state.model,
      mode: state.mode,
      concurrency: state.mode === 'sequential' ? 1 : state.concurrency,
      calls: ids.length,
      completed: 0,
      parseErrors: 0,
      failed: 0,
      cancelled: 0,
      cost: 0,
      missingCost: 0,
      status: 'running',
      terminalCrops: new Set(),
    }
    entries.push(entry)
    ids.forEach(id => cropEntries.set(id, entry))
  }
  state.history.unshift(...entries)
  state.activeHistory = { runId, entries, cropEntries }
  return state.activeHistory
}

function recordHistoryEvent(context, event) {
  if (!event?.crop_id || !['completed', 'parse_error', 'failed', 'cancelled'].includes(event.type)) return
  const entry = context.cropEntries.get(event.crop_id)
  if (!entry || entry.terminalCrops.has(event.crop_id)) return
  entry.terminalCrops.add(event.crop_id)
  if (event.type === 'completed') entry.completed += 1
  else if (event.type === 'parse_error') entry.parseErrors += 1
  else if (event.type === 'failed') entry.failed += 1
  else entry.cancelled += 1
  const cost = Number(event.cost)
  if (event.cost != null && Number.isFinite(cost)) entry.cost += cost
  else entry.missingCost += 1
}

function finishHistory(context, stopped = false) {
  for (const entry of context.entries) {
    const unfinished = entry.calls - entry.terminalCrops.size
    if (unfinished > 0) {
      entry.cancelled += unfinished
      entry.missingCost += unfinished
    }
    if (stopped) entry.status = 'stopped'
    else if (entry.completed === entry.calls) entry.status = 'completed'
    else entry.status = 'partial'
  }
  if (state.activeHistory?.runId === context.runId) state.activeHistory = null
}

function render() {
  if (!state.dataset) {
    root.innerHTML = '<main class="loading">Loading dental image catalog…</main>'
    return
  }
  const available = images()
  const image = currentImage()
  const failed = Object.values(state.results).filter(result => ['failed', 'parse_error'].includes(result.type)).length
  const allSelected = image?.crops.length && image.crops.every(crop => state.selected.has(crop.crop_id))
  root.innerHTML = `<main class="app-shell ${state.leftPanelOpen ? '' : 'panel-collapsed'}">
    <aside class="editor-panel">
      <button id="togglePanel" class="panel-toggle" aria-label="${state.leftPanelOpen ? 'Collapse' : 'Expand'} settings panel" title="${state.leftPanelOpen ? 'Collapse' : 'Expand'} settings">${state.leftPanelOpen ? '‹' : '›'}</button>
      <div class="editor-content">
        <header><p class="eyebrow">Evaluation workspace</p><h1>Dental Finding Lab</h1><p class="muted">${state.dataset.image_count.toLocaleString()} images · ${state.dataset.crop_count.toLocaleString()} tooth boxes</p></header>
        <details id="configAccordion" class="config-accordion" ${state.configOpen ? 'open' : ''}>
          <summary><span>Prompt & model settings</span><small>${escapeHtml(state.model)}</small></summary>
          <div class="config-content">
            <label>System prompt<textarea id="prompt" class="prompt">${escapeHtml(state.prompt)}</textarea></label>
            <div class="prompt-actions"><span id="promptSaveStatus" class="prompt-save-status ${state.promptDirty ? 'dirty' : ''}">${escapeHtml(state.promptSaveStatus)}</span><button id="savePrompt" ${!state.promptDirty || state.promptSaveStatus === 'Saving…' || state.running ? 'disabled' : ''}>Save ${escapeHtml(findingLabel())} prompt</button></div>
            <label>Output schema<textarea id="schema" class="schema" spellcheck="false">${escapeHtml(state.schemaText)}</textarea></label>
            <div class="settings-grid">
              <label class="wide">Model ID<input id="model" value="${escapeHtml(state.model)}" /></label>
              <label>Max tokens<input id="maxTokens" type="number" min="1" max="16384" value="${state.maxTokens}" /></label>
              <label>Padding<input id="padding" type="number" min="0" max="1" step="0.05" value="${state.padding}" /></label>
              <label>Max edge<input id="maxEdge" type="number" min="128" max="4096" step="64" value="${state.maxEdge}" /></label>
            </div>
          </div>
        </details>
      </div>
    </aside>
    <section class="workspace">
      <div class="toolbar">
        <button id="upload" ${state.uploading ? 'disabled' : ''}>${state.uploading ? 'Detecting teeth…' : '↑ Upload image'}</button>
        <input id="uploadInput" type="file" accept="image/jpeg,image/png,image/webp" hidden />
        <label class="finding-control">Finding <select id="finding" ${state.running ? 'disabled' : ''}><option value="stain" ${state.finding === 'stain' ? 'selected' : ''}>Stain</option><option value="calculus" ${state.finding === 'calculus' ? 'selected' : ''}>Calculus</option><option value="caries" ${state.finding === 'caries' ? 'selected' : ''}>Caries</option></select></label>
        <div class="search"><span>⌕</span><input id="search" placeholder="Find image ID" value="${escapeHtml(state.query)}" /></div>
        <div class="pager"><button id="previous" ${state.imageIndex === 0 ? 'disabled' : ''}>‹</button><span>${available.length ? state.imageIndex + 1 : 0} / ${available.length}</span><button id="next" ${state.imageIndex >= available.length - 1 ? 'disabled' : ''}>›</button></div>
        <select id="mode"><option value="parallel" ${state.mode === 'parallel' ? 'selected' : ''}>Parallel</option><option value="sequential" ${state.mode === 'sequential' ? 'selected' : ''}>Sequential</option></select>
        <label class="inline">Concurrency <input id="concurrency" type="range" min="1" max="32" value="${state.concurrency}" ${state.mode === 'sequential' ? 'disabled' : ''}/><b>${state.mode === 'sequential' ? 1 : state.concurrency}</b></label>
        <button id="run" class="primary" ${!state.selected.size || state.running ? 'disabled' : ''}>▶ Run selected (${state.selected.size})</button>
        ${state.running ? '<button id="stop" class="danger">■ Stop</button>' : `<button id="retry" ${failed ? '' : 'disabled'}>↻ Retry failed</button>`}
        <button id="openHistory" class="history-button">History <span>${state.history.length}</span></button>
      </div>
      ${state.banner ? `<div class="banner">⚠ ${escapeHtml(state.banner)}<button id="closeBanner">×</button></div>` : ''}
      ${image ? `<div class="image-heading"><div><p class="eyebrow">Source image</p><h2>${escapeHtml(image.image_id)}</h2></div><button id="selectAll">${allSelected ? 'Clear image' : 'Select all teeth'}</button></div><div class="grid-scroll">${cropCards(image)}${detail(image)}${sourceOverview(image)}</div>` : '<div class="empty">No matching image.</div>'}
    </section>
    ${historyDialog()}
  </main>`
  bindEvents()
  if (state.historyOpen) document.querySelector('#historyDialog')?.showModal()
}

function bindEvents() {
  const changeImage = updateIndex => {
    state.imageIndex = updateIndex(state.imageIndex)
    state.selected.clear()
    state.activeCrop = null
    render()
  }
  const update = (id, key, transform = value => value) => document.querySelector(`#${id}`)?.addEventListener('input', event => { state[key] = transform(event.target.value) })
  document.querySelector('#upload')?.addEventListener('click', () => document.querySelector('#uploadInput')?.click())
  document.querySelector('#uploadInput')?.addEventListener('change', event => {
    const file = event.target.files?.[0]
    if (file) uploadImage(file)
  })
  document.querySelector('#togglePanel')?.addEventListener('click', () => { state.leftPanelOpen = !state.leftPanelOpen; render() })
  document.querySelector('#configAccordion')?.addEventListener('toggle', event => { state.configOpen = event.currentTarget.open })
  document.querySelector('#prompt')?.addEventListener('input', event => {
    state.prompt = event.target.value
    state.promptDirty = state.prompt !== state.prompts[state.finding]
    state.promptSaveStatus = state.promptDirty ? 'Unsaved changes' : 'Saved'
    const status = document.querySelector('#promptSaveStatus')
    const button = document.querySelector('#savePrompt')
    if (status) { status.textContent = state.promptSaveStatus; status.classList.toggle('dirty', state.promptDirty) }
    if (button) button.disabled = !state.promptDirty || state.running
  })
  document.querySelector('#savePrompt')?.addEventListener('click', saveCurrentPrompt)
  update('schema', 'schemaText'); update('model', 'model'); update('maxTokens', 'maxTokens', Number); update('maxEdge', 'maxEdge', Number)
  document.querySelector('#padding')?.addEventListener('change', event => { state.padding = Number(event.target.value); render() })
  document.querySelector('#search')?.addEventListener('input', event => {
    state.query = event.target.value
    state.imageIndex = 0
    state.selected.clear()
    state.activeCrop = null
    const caret = state.query.length
    render()
    const input = document.querySelector('#search')
    input?.focus()
    input?.setSelectionRange(caret, caret)
  })
  document.querySelector('#finding')?.addEventListener('change', event => {
    const nextFinding = event.target.value
    if (state.promptDirty && !globalThis.confirm(`Discard unsaved changes to the ${state.finding} prompt?`)) {
      event.target.value = state.finding
      return
    }
    state.finding = nextFinding
    state.prompt = state.prompts[nextFinding]
    state.promptDirty = false
    state.promptSaveStatus = 'Saved'
    state.results = {}
    state.enhanced = {}
    state.banner = ''
    render()
  })
  document.querySelector('#mode')?.addEventListener('change', event => { state.mode = event.target.value; render() })
  document.querySelector('#concurrency')?.addEventListener('change', event => { state.concurrency = Number(event.target.value); render() })
  document.querySelector('#previous')?.addEventListener('click', () => changeImage(index => Math.max(0, index - 1)))
  document.querySelector('#next')?.addEventListener('click', () => changeImage(index => Math.min(images().length - 1, index + 1)))
  document.querySelector('#closeBanner')?.addEventListener('click', () => { state.banner = ''; render() })
  document.querySelector('#openHistory')?.addEventListener('click', () => { state.historyOpen = true; document.querySelector('#historyDialog')?.showModal() })
  document.querySelector('#closeHistory')?.addEventListener('click', () => { state.historyOpen = false; document.querySelector('#historyDialog')?.close() })
  document.querySelector('#historyDialog')?.addEventListener('close', () => { state.historyOpen = false })
  document.querySelector('#historyDialog')?.addEventListener('click', event => {
    if (event.target === event.currentTarget) { state.historyOpen = false; event.currentTarget.close() }
  })
  document.querySelector('#clearHistory')?.addEventListener('click', () => { state.history = []; render() })
  document.querySelectorAll('[data-crop]').forEach(card => card.addEventListener('click', () => {
    const id = card.dataset.crop
    state.activeCrop = id
    state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id)
    render()
  }))
  document.querySelectorAll('[data-enhance]').forEach(button => button.addEventListener('click', event => {
    event.stopPropagation()
    enhanceOrToggle(button.dataset.enhance)
  }))
  document.querySelectorAll('[data-overview-crop]').forEach(box => box.addEventListener('click', () => {
    const id = box.dataset.overviewCrop
    state.activeCrop = id
    state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id)
    render()
  }))
  document.querySelector('#selectAll')?.addEventListener('click', () => {
    const image = currentImage()
    const clear = image.crops.every(crop => state.selected.has(crop.crop_id))
    image.crops.forEach(crop => clear ? state.selected.delete(crop.crop_id) : state.selected.add(crop.crop_id))
    render()
  })
  document.querySelector('#run')?.addEventListener('click', () => run([...state.selected]))
  document.querySelector('#stop')?.addEventListener('click', () => state.controller?.abort())
  document.querySelector('#retry')?.addEventListener('click', () => run(Object.values(state.results).filter(result => ['failed', 'parse_error'].includes(result.type)).map(result => result.crop_id)))
}

async function saveCurrentPrompt() {
  if (!state.promptDirty || state.running || state.promptSaveStatus === 'Saving…') return
  const finding = state.finding
  const prompt = state.prompt
  state.promptSaveStatus = 'Saving…'
  render()
  try {
    const response = await fetch(`/api/prompts/${finding}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || `Prompt save failed (${response.status})`)
    state.prompts[finding] = body.prompt
    if (state.finding === finding) {
      state.prompt = body.prompt
      state.promptDirty = false
      state.promptSaveStatus = 'Saved'
    }
  } catch (error) {
    state.promptSaveStatus = 'Save failed'
    state.banner = error.message
  } finally {
    render()
  }
}

async function uploadImage(file) {
  if (state.uploading) return
  state.uploading = true
  state.banner = ''
  render()
  try {
    const response = await fetch('/api/images/upload', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) },
      body: file,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || `Upload failed (${response.status})`)
    const image = { ...body.image, uploaded: true }
    state.dataset.images.unshift(image)
    state.dataset.image_count += 1
    state.dataset.crop_count += image.crop_count
    state.query = ''
    state.imageIndex = 0
    state.selected.clear()
    state.activeCrop = null
    if (!image.crop_count) state.banner = 'The tooth detector completed but found no tooth boxes.'
  } catch (error) {
    state.banner = error.message
  } finally {
    state.uploading = false
    render()
  }
}

async function enhanceOrToggle(cropId) {
  const current = state.enhanced[cropId]
  if (current?.status === 'loading') return
  if (current?.status === 'ready') {
    current.shown = !current.shown
    render()
    return
  }
  state.enhanced[cropId] = { status: 'loading', shown: false }
  state.banner = ''
  render()
  const startedAt = performance.now()
  try {
    const response = await fetch(`/api/crops/${encodeURIComponent(cropId)}/enhance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ padding: state.padding, max_edge: state.maxEdge }),
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || `Enhance failed (${response.status})`)
    state.enhanced[cropId] = { status: 'ready', image: body.image, shown: true }
    recordEnhanceHistory(cropId, { ok: true, body, clientMs: Math.round(performance.now() - startedAt) })
  } catch (error) {
    state.enhanced[cropId] = { status: 'failed', shown: false, error: error.message }
    state.banner = error.message
    recordEnhanceHistory(cropId, { ok: false, error: error.message })
  } finally {
    render()
  }
}

function parseSseBlock(block) {
  const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
  return data ? JSON.parse(data) : null
}

async function run(cropIds) {
  if (!cropIds.length || state.running) return
  let schema
  try { schema = JSON.parse(state.schemaText) } catch { state.banner = 'Output schema is not valid JSON.'; render(); return }
  state.banner = ''
  state.running = true
  cropIds.forEach(id => { state.results[id] = { type: 'queued', crop_id: id } })
  const enhanced = {}
  cropIds.forEach(id => {
    const entry = state.enhanced[id]
    if (entry?.status === 'ready' && entry.shown) enhanced[id] = entry.image
  })
  const historyContext = beginHistory(cropIds)
  const controller = new AbortController()
  state.controller = controller
  render()
  try {
    const response = await fetch('/api/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ crop_ids: cropIds, prompt: state.prompt, schema, model: state.model, finding: state.finding, max_tokens: state.maxTokens, max_edge: state.maxEdge, padding: state.padding, mode: state.mode, concurrency: state.concurrency, enhanced }),
    })
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Evaluation failed (${response.status})`) }
    if (!response.body) throw new Error('Streaming is unavailable in this browser')
    const reader = response.body.getReader(), decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      const blocks = buffer.split('\n\n'); buffer = blocks.pop() || ''
      for (const block of blocks) {
        const event = parseSseBlock(block)
        if (event?.crop_id) {
          state.results[event.crop_id] = event
          recordHistoryEvent(historyContext, event)
        }
        if (event?.type === 'rate_limited') state.banner = `OpenRouter rate limited a request; retrying in ${event.retry_in}s.`
      }
      render()
      if (done) break
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      cropIds.forEach(id => {
        if (['queued', 'running', 'rate_limited'].includes(state.results[id]?.type)) {
          const event = { type: 'cancelled', crop_id: id }
          state.results[id] = event
          recordHistoryEvent(historyContext, event)
        }
      })
    } else state.banner = error.message
  } finally {
    finishHistory(historyContext, controller.signal.aborted)
    state.running = false; state.controller = null; render()
  }
}

fetch('/dataset.json').then(response => {
  if (!response.ok) throw new Error(`Dataset request failed (${response.status})`)
  return response.json()
}).then(dataset => {
  state.dataset = dataset
  state.model = dataset.defaults.model
  state.finding = dataset.defaults.finding
  state.prompts = dataset.defaults.prompts
  state.prompt = state.prompts[state.finding]
  state.schemaText = JSON.stringify(dataset.defaults.schema, null, 2)
  render()
}).catch(error => { root.innerHTML = `<main class="center-error">⚠ ${escapeHtml(error.message)}</main>` })

render()
