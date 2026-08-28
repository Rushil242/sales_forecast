/**
 * API client.
 *
 * Requests go to a relative /api path, which Vite proxies to the backend in
 * development and any reverse proxy handles in production. That keeps the
 * browser on a single origin, so there is no CORS negotiation on the hot path
 * and no build-time host to configure.
 */

const PREFIX = '/api/v1'

/**
 * The backend returns a structured `{ error: { code, message, details } }` body.
 * This surfaces `code` and `details` on the thrown Error so callers can branch on
 * the failure kind rather than matching on message text.
 */
export class ApiError extends Error {
  constructor(message, { code, details, status, requestId } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code ?? 'unknown_error'
    this.details = details ?? {}
    this.status = status
    this.requestId = requestId
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch (cause) {
    throw new ApiError(
      'Could not reach the API. Is the backend running on port 8000?',
      { code: 'network_error' },
    )
  }

  const isJson = (response.headers.get('content-type') || '').includes('application/json')
  const payload = isJson ? await response.json() : null

  if (!response.ok) {
    const error = payload?.error

    // A non-JSON 5xx from a /api path means the dev proxy could not reach the
    // API at all — the backend is down, not the request. Saying "status 500"
    // sends people hunting through application logs for a server that is not
    // running, so name the actual problem.
    if (!error && response.status >= 500) {
      throw new ApiError(
        'The RetailIQ API is not responding. Start it with ./run.sh in the project ' +
        'folder, then try again.',
        { code: 'backend_unavailable', status: response.status },
      )
    }

    throw new ApiError(error?.message || `Request failed with status ${response.status}`, {
      code: error?.code,
      details: error?.details,
      status: response.status,
      requestId: error?.request_id,
    })
  }

  return payload
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  ready: () => request('/ready'),

  listModels: () => request(`${PREFIX}/models`),

  listDatasets: () => request(`${PREFIX}/datasets`),

  describeDataset: (identifier) =>
    request(`${PREFIX}/datasets/${encodeURI(identifier)}`),

  uploadDataset: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`${PREFIX}/datasets/upload`, { method: 'POST', body: form })
  },

  datasetTaxonomy: (identifier) =>
    request(`${PREFIX}/datasets/${encodeURI(identifier)}/taxonomy`),

  forecast: (body) => request(`${PREFIX}/forecast`, json(body)),

  /**
   * Run a forecast over server-sent events, reporting each pipeline stage as the
   * backend actually reaches it.
   *
   * The stages are not simulated on a timer here: the server emits them from
   * inside the pipeline, so a skipped stage never arrives and a slow one is
   * visibly slow. Falls back to the plain POST if streaming is unavailable.
   */
  forecastStream: async (body, onStage) => {
    let response
    try {
      response = await fetch(`${PREFIX}/forecast/stream`, json(body))
    } catch {
      return api.forecast(body)
    }
    if (!response.ok || !response.body) return api.forecast(body)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by a blank line.
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const line = frame.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        let message
        try { message = JSON.parse(line.slice(6)) } catch { continue }

        if (message.type === 'stage') onStage?.(message)
        else if (message.type === 'done') return message.result
        else if (message.type === 'error') {
          throw new ApiError(message.error?.message ?? 'The forecast failed.', {
            code: message.error?.code, details: message.error?.details,
          })
        }
      }
    }
    throw new ApiError('The forecast stream ended without a result.', {
      code: 'stream_incomplete',
    })
  },


  social: ({ query, lookbackDays = 30, refresh = false }) => {
    const params = new URLSearchParams({
      query,
      lookback_days: String(lookbackDays),
      refresh: String(refresh),
    })
    return request(`${PREFIX}/social?${params}`)
  },

  connectors: () => request(`${PREFIX}/social/connectors`),

  // ── data connectors ──────────────────────────────────────────────────────
  dataConnectors: () => request(`${PREFIX}/connectors`),

  /**
   * Ask the API for the platform's own consent URL rather than following a
   * redirect through fetch. The browser must travel to Shopify or Zoho itself --
   * that is the whole point of OAuth, and an XHR cannot show a consent screen.
   */
  connectStart: (provider, shop = '') => {
    const params = new URLSearchParams({ json: 'true' })
    if (shop) params.set('shop', shop)
    return request(`${PREFIX}/connect/${provider}/start?${params}`)
  },

  syncConnector: (accountId, days) => {
    const params = days ? `?days=${days}` : ''
    return request(`${PREFIX}/connectors/${accountId}/sync${params}`, { method: 'POST' })
  },

  disconnectConnector: (accountId) =>
    request(`${PREFIX}/connectors/${accountId}`, { method: 'DELETE' }),

  runs: (limit = 25) => request(`${PREFIX}/runs?limit=${limit}`),
}
