const configuredBase = import.meta.env.VITE_VEYRO_API_BASE_URL || ''
const base = configuredBase.replace(/\/$/, '')

async function request(path, options) {
  let response
  try {
    response = await fetch(`${base}${path}`, options)
  } catch {
    throw new Error('Cannot reach the Veyro API. Check that the backend is running.')
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch { /* Keep the HTTP status message. */ }
    throw new Error(detail)
  }
  return response.json()
}

export function submitCheck({ files, listingUrl, sellerName }) {
  const data = new FormData()
  data.append('metadata', JSON.stringify({
    listing_url: listingUrl.trim() || null,
    seller_name: sellerName.trim() || null,
  }))
  files.forEach((file) => data.append('photos', file))
  return request('/v1/authenticity/checks', { method: 'POST', body: data })
}

export function identifyCheck(checkId) {
  return request(`/v1/authenticity/checks/${encodeURIComponent(checkId)}/identify`, { method: 'POST' })
}

export function getEvidence(checkId) {
  return request(`/v1/authenticity/checks/${encodeURIComponent(checkId)}/evidence`)
}

export function getAssessment(checkId) {
  return request(`/v1/authenticity/checks/${encodeURIComponent(checkId)}/assessment`)
}
