const CSRF = { 'X-Requested-With': 'snackdrop' }

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

function detailMessage(detail, fallback) {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  return fallback
}

async function request(method, url, body) {
  const opts = { method, credentials: 'same-origin', headers: { ...CSRF } }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  if (res.status === 204) return null
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) throw new ApiError(res.status, detailMessage(data?.detail, `Error ${res.status}`))
  return data
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  patch: (url, body) => request('PATCH', url, body),
  del: (url) => request('DELETE', url),

  /** Sube archivos con progreso (fetch no expone progreso de subida). */
  upload(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url)
      xhr.withCredentials = true
      xhr.setRequestHeader('X-Requested-With', 'snackdrop')
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
      xhr.onload = () => {
        let data = null
        try {
          data = JSON.parse(xhr.responseText)
        } catch {
          data = null
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data)
        else reject(new ApiError(xhr.status, detailMessage(data?.detail, `Error ${xhr.status}`)))
      }
      xhr.onerror = () => reject(new ApiError(0, 'Error de red'))
      xhr.send(formData)
    })
  },
}
