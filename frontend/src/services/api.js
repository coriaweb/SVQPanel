/**
 * API Client for SVQPanel
 */

const API_BASE_URL = 'http://localhost:8001'

class APIClient {
  constructor(baseURL = API_BASE_URL) {
    this.baseURL = baseURL
    this.token = localStorage.getItem('token')
  }

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json'
    }
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`
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
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'API Error')
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
  getUsers(skip = 0, limit = 10) {
    return this.get(`/api/users?skip=${skip}&limit=${limit}`)
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

  changePHPVersion(domainId, phpVersion) {
    return this.put(`/api/domains/${domainId}/php`, { php_version: phpVersion })
  }

  // PHP
  getPHPVersions() {
    return this.get('/api/php/versions')
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

  // Health check
  health() {
    return this.get('/api/health')
  }
}

export default new APIClient()
