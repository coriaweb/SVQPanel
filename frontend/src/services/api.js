/**
 * API Client for SVQPanel
 */

const API_BASE_URL = ''

class APIClient {
  constructor(baseURL = API_BASE_URL) {
    this.baseURL = baseURL
    this.token = localStorage.getItem('token')
  }

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json'
    }
    const token = localStorage.getItem('token') || this.token
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return headers
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`
    const config = {
      headers: this.getHeaders(),
      ...options
    }

    try {
      const response = await fetch(url, config)

      // 204 No Content no tiene body
      let data = null
      if (response.status !== 204) {
        const contentType = response.headers.get('content-type') || ''
        if (contentType.includes('application/json')) {
          data = await response.json()
        } else {
          // El servidor devolvió HTML (nginx error, 502, etc.) en lugar de JSON
          const text = await response.text()
          throw new Error(`Error ${response.status}: el servidor no está disponible`)
        }
      }

      if (!response.ok) {
        // Si es 401, limpiar token y redirigir a login
        if (response.status === 401) {
          localStorage.removeItem('token')
          localStorage.removeItem('user')
          window.location.href = '/login'
          throw new Error('Sesión expirada. Por favor inicia sesión nuevamente.')
        }
        // data.detail puede ser string (error normal) o array (errores de validación Pydantic)
        let errorMessage
        if (Array.isArray(data?.detail)) {
          errorMessage = data.detail.map(e => `${e.loc?.slice(-1)[0] ?? ''}: ${e.msg}`).join(' | ')
        } else {
          errorMessage = data?.detail || `Error ${response.status}`
        }
        throw new Error(errorMessage)
      }

      return data
    } catch (error) {
      console.error('API Error:', error)
      throw error
    }
  }

  async get(endpoint) {
    return this.request(endpoint, { method: 'GET' })
  }

  async post(endpoint, body) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(body)
    })
  }

  async put(endpoint, body) {
    return this.request(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body)
    })
  }

  async delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' })
  }

  // Users
  getUsers(skip = 0, limit = 100, userId = null, parentId = null) {
    let url = `/api/users?skip=${skip}&limit=${limit}`
    if (userId) url += `&user_id=${userId}`
    if (parentId) url += `&parent_id=${parentId}`
    return this.get(url)
  }

  getUser(userId) {
    return this.get(`/api/users/${userId}`)
  }

  createUser(userData) {
    return this.post('/api/users', userData)
  }

  updateUser(userId, userData) {
    return this.put(`/api/users/${userId}`, userData)
  }

  deleteUser(userId) {
    return this.delete(`/api/users/${userId}`)
  }

  // Domains
  getDomains(userId = null, skip = 0, limit = 10) {
    let endpoint = `/api/domains?skip=${skip}&limit=${limit}`
    if (userId) {
      endpoint += `&user_id=${userId}`
    }
    return this.get(endpoint)
  }

  getDomain(domainId) {
    return this.get(`/api/domains/${domainId}`)
  }

  createDomain(domainData) {
    return this.post('/api/domains', domainData)
  }

  updateDomain(domainId, domainData) {
    return this.put(`/api/domains/${domainId}`, domainData)
  }

  deleteDomain(domainId) {
    return this.delete(`/api/domains/${domainId}`)
  }

  // PHP versions (available/running — used in domain PHP selector)
  getPHPVersions() {
    return this.get('/api/php/versions')
  }

  // PHP management (admin) — install/enable/disable/uninstall
  getPHPVersionsStatus() {
    return this.get('/api/php/versions/status')
  }

  installPHPVersion(version) {
    return this.post(`/api/php/versions/${version}/install`, {})
  }

  enablePHPVersion(version) {
    return this.post(`/api/php/versions/${version}/enable`, {})
  }

  disablePHPVersion(version) {
    return this.post(`/api/php/versions/${version}/disable`, {})
  }

  uninstallPHPVersion(version) {
    return this.delete(`/api/php/versions/${version}`)
  }

  changePHPVersion(domainId, phpVersion) {
    return this.put(`/api/domains/${domainId}/php`, {
      php_version: phpVersion
    })
  }

  // SSL
  createSSL(domainId, sslData) {
    return this.post(`/api/domains/${domainId}/ssl`, sslData)
  }

  getSSL(domainId) {
    return this.get(`/api/domains/${domainId}/ssl`)
  }

  deleteSSL(domainId) {
    return this.delete(`/api/domains/${domainId}/ssl`)
  }

  // IPv6
  assignIPv6(domainId, ipv6Data) {
    return this.post(`/api/domains/${domainId}/ipv6`, ipv6Data)
  }

  getIPv6(domainId) {
    return this.get(`/api/domains/${domainId}/ipv6`)
  }

  deleteIPv6(domainId) {
    return this.delete(`/api/domains/${domainId}/ipv6`)
  }

  // Settings
  getSettings() {
    return this.get('/api/settings')
  }

  updateSettings(data) {
    return this.put('/api/settings', data)
  }

  getNextIPv6() {
    return this.get('/api/settings/next-ipv6')
  }

  // Health check
  health() {
    return this.get('/api/health')
  }

  // Authentication
  login(credentials) {
    return this.post('/api/auth/login', credentials)
  }

  logout() {
    return this.post('/api/auth/logout', {})
  }

  getCurrentUser() {
    return this.get('/api/auth/me')
  }

  changePassword(data) {
    return this.post('/api/auth/change-password', data)
  }
}

export default new APIClient()
