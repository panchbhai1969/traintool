const state = {
  dataset: null,
  query: '',
  imageIndex: 0,
  selected: new Set(),
  results: {},
  activeCrop: null,
  prompt: 'You are evaluating a crop of one tooth from a dental photograph for extrinsic stain. Use adjacent enamel and the gingival margin as context. Distinguish stain from shadow, calculus, restoration margins, and caries. Be conservative when visual evidence is ambiguous.',
  schemaText: '',
  model: '',
  temperature: 0,
  maxTokens: 800,
  maxEdge: 896,
  padding: .25,
  mode: 'parallel',
  concurrency: 8,
  running: false,
  banner: '',
  controller: null,
}

const root = document.querySelector('#root')

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character])
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

function resultClass(event) {
  if (!event) return ''
  if (event.type === 'completed') return event.result?.stain_present ? 'positive' : 'negative'
  if (event.type === 'failed' || event.type === 'parse_error') return 'errored'
  if (['running', 'queued', 'rate_limited'].includes(event.type)) return 'working'
  return ''
}

function cropCards(image) {
  if (!image.crops.length) return '<div class="empty">No tooth boxes found for this image.</div>'
  return `<div class="crop-grid">${image.crops.map((crop, index) => {
    const event = state.results[crop.crop_id]
    const confidence = typeof event?.result?.confidence === 'number' ? `${Math.round(event.result.confidence * 100)}%` : ''
    return `<article class="crop-card ${state.selected.has(crop.crop_id) ? 'selected' : ''} ${resultClass(event)}" data-crop="${escapeHtml(crop.crop_id)}">
      <div class="crop-frame">${cropSvg(image, crop)}</div>
      <div class="crop-meta"><span>Tooth ${index + 1}</span><span class="status">${escapeHtml(event?.type?.replace('_', ' ') || 'ready')}</span></div>
      ${event?.result ? `<div class="verdict"><b>${event.result.stain_present ? 'Stain' : 'Clear'}</b><span>${confidence}</span></div>` : ''}
    </article>`
  }).join('')}</div>`
}

function detail(image) {
  const crop = image.crops.find(item => item.crop_id === state.activeCrop)
  if (!crop) return ''
  const event = state.results[crop.crop_id]
  const body = event ? JSON.stringify(event.result || { error: event.error, raw: event.raw }, null, 2) : ''
  return `<section class="detail"><div class="detail-image">${cropSvg(image, crop)}</div><div>
    <p class="eyebrow">Selected tooth</p><h3>${escapeHtml(crop.crop_id)}</h3>
    ${event ? `<div class="metrics"><span>${event.latency_ms ? `${event.latency_ms} ms` : '—'}</span><span>${event.prompt_tokens ?? '—'} prompt tokens</span><span>${event.completion_tokens ?? '—'} completion tokens</span><span>${event.cost != null ? `$${event.cost}` : 'cost unavailable'}</span></div><pre>${escapeHtml(body)}</pre>` : '<p class="muted">Run this crop to inspect its structured response.</p>'}
  </div></section>`
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
  root.innerHTML = `<main class="app-shell">
    <aside class="editor-panel">
      <header><p class="eyebrow">Evaluation workspace</p><h1>Stain Prompt Lab</h1><p class="muted">${state.dataset.image_count.toLocaleString()} images · ${state.dataset.crop_count.toLocaleString()} tooth boxes</p></header>
      <label>System prompt<textarea id="prompt" class="prompt">${escapeHtml(state.prompt)}</textarea></label>
      <label>Output schema<textarea id="schema" class="schema" spellcheck="false">${escapeHtml(state.schemaText)}</textarea></label>
      <div class="settings-grid">
        <label class="wide">Model ID<input id="model" value="${escapeHtml(state.model)}" /></label>
        <label>Temperature<input id="temperature" type="number" min="0" max="2" step="0.1" value="${state.temperature}" /></label>
        <label>Max tokens<input id="maxTokens" type="number" min="1" max="16384" value="${state.maxTokens}" /></label>
        <label>Padding<input id="padding" type="number" min="0" max="1" step="0.05" value="${state.padding}" /></label>
        <label>Max edge<input id="maxEdge" type="number" min="128" max="4096" step="64" value="${state.maxEdge}" /></label>
      </div>
    </aside>
    <section class="workspace">
      <div class="toolbar">
        <div class="search"><span>⌕</span><input id="search" placeholder="Find image ID" value="${escapeHtml(state.query)}" /></div>
        <div class="pager"><button id="previous" ${state.imageIndex === 0 ? 'disabled' : ''}>‹</button><span>${available.length ? state.imageIndex + 1 : 0} / ${available.length}</span><button id="next" ${state.imageIndex >= available.length - 1 ? 'disabled' : ''}>›</button></div>
        <select id="mode"><option value="parallel" ${state.mode === 'parallel' ? 'selected' : ''}>Parallel</option><option value="sequential" ${state.mode === 'sequential' ? 'selected' : ''}>Sequential</option></select>
        <label class="inline">Concurrency <input id="concurrency" type="range" min="1" max="32" value="${state.concurrency}" ${state.mode === 'sequential' ? 'disabled' : ''}/><b>${state.mode === 'sequential' ? 1 : state.concurrency}</b></label>
        <button id="run" class="primary" ${!state.selected.size || state.running ? 'disabled' : ''}>▶ Run selected (${state.selected.size})</button>
        ${state.running ? '<button id="stop" class="danger">■ Stop</button>' : `<button id="retry" ${failed ? '' : 'disabled'}>↻ Retry failed</button>`}
      </div>
      ${state.banner ? `<div class="banner">⚠ ${escapeHtml(state.banner)}<button id="closeBanner">×</button></div>` : ''}
      ${image ? `<div class="image-heading"><div><p class="eyebrow">Source image</p><h2>${escapeHtml(image.image_id)}</h2></div><button id="selectAll">${allSelected ? 'Clear image' : 'Select all teeth'}</button></div><div class="grid-scroll">${cropCards(image)}${detail(image)}</div>` : '<div class="empty">No matching image.</div>'}
    </section>
  </main>`
  bindEvents()
}

function bindEvents() {
  const update = (id, key, transform = value => value) => document.querySelector(`#${id}`)?.addEventListener('input', event => { state[key] = transform(event.target.value) })
  update('prompt', 'prompt'); update('schema', 'schemaText'); update('model', 'model'); update('temperature', 'temperature', Number); update('maxTokens', 'maxTokens', Number); update('maxEdge', 'maxEdge', Number)
  document.querySelector('#padding')?.addEventListener('change', event => { state.padding = Number(event.target.value); render() })
  document.querySelector('#search')?.addEventListener('input', event => {
    state.query = event.target.value
    state.imageIndex = 0
    const caret = state.query.length
    render()
    const input = document.querySelector('#search')
    input?.focus()
    input?.setSelectionRange(caret, caret)
  })
  document.querySelector('#mode')?.addEventListener('change', event => { state.mode = event.target.value; render() })
  document.querySelector('#concurrency')?.addEventListener('change', event => { state.concurrency = Number(event.target.value); render() })
  document.querySelector('#previous')?.addEventListener('click', () => { state.imageIndex = Math.max(0, state.imageIndex - 1); render() })
  document.querySelector('#next')?.addEventListener('click', () => { state.imageIndex = Math.min(images().length - 1, state.imageIndex + 1); render() })
  document.querySelector('#closeBanner')?.addEventListener('click', () => { state.banner = ''; render() })
  document.querySelectorAll('[data-crop]').forEach(card => card.addEventListener('click', () => {
    const id = card.dataset.crop
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
  const controller = new AbortController()
  state.controller = controller
  render()
  try {
    const response = await fetch('/api/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ crop_ids: cropIds, prompt: state.prompt, schema, model: state.model, temperature: state.temperature, max_tokens: state.maxTokens, max_edge: state.maxEdge, padding: state.padding, mode: state.mode, concurrency: state.concurrency }),
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
        if (event?.crop_id) state.results[event.crop_id] = event
        if (event?.type === 'rate_limited') state.banner = `OpenRouter rate limited a request; retrying in ${event.retry_in}s.`
      }
      render()
      if (done) break
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      cropIds.forEach(id => {
        if (['queued', 'running', 'rate_limited'].includes(state.results[id]?.type)) state.results[id] = { type: 'cancelled', crop_id: id }
      })
    } else state.banner = error.message
  } finally {
    state.running = false; state.controller = null; render()
  }
}

fetch('/dataset.json').then(response => {
  if (!response.ok) throw new Error(`Dataset request failed (${response.status})`)
  return response.json()
}).then(dataset => {
  state.dataset = dataset
  state.model = dataset.defaults.model
  state.schemaText = JSON.stringify(dataset.defaults.schema, null, 2)
  render()
}).catch(error => { root.innerHTML = `<main class="center-error">⚠ ${escapeHtml(error.message)}</main>` })

render()
