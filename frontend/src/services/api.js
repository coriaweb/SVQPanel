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

  // File Manager
  getFileManagerDomains() {
    return this.get('/api/file-manager/domains')
  }

  listDomainFiles(domainId, path = '') {
    return this.get(`/api/file-manager/domains/${domainId}/files?path=${encodeURIComponent(path || '')}`)
  }

  readDomainFile(domainId, path) {
    return this.get(`/api/file-manager/domains/${domainId}/file?path=${encodeURIComponent(path)}`)
  }

  writeDomainFile(domainId, path, content) {
    return this.put(`/api/file-manager/domains/${domainId}/file?path=${encodeURIComponent(path)}`, { content })
  }

  createDomainDirectory(domainId, path, name) {
    return this.post(`/api/file-manager/domains/${domainId}/mkdir`, { path, name })
  }

  renameDomainEntry(domainId, path, newName) {
    return this.post(`/api/file-manager/domains/${domainId}/rename`, { path, new_name: newName })
  }

  deleteDomainEntry(domainId, path) {
    return this.post(`/api/file-manager/domains/${domainId}/delete`, { path })
  }

  /**
   * Sube archivos con soporte de progreso real vía XMLHttpRequest.
   * @param {number} domainId
   * @param {string} path  - carpeta destino relativa
   * @param {FileList|File[]} files
   * @param {(percent: number) => void} [onProgress] - callback 0–100
   */
  uploadDomainFiles(domainId, path, files, onProgress = null, overwrite = true) {
    return new Promise((resolve, reject) => {
      const formData = new FormData()
      formData.append('path', path || '')
      formData.append('overwrite', overwrite ? 'true' : 'false')
      Array.from(files || []).forEach(file => formData.append('files', file))

      const xhr = new XMLHttpRequest()
      xhr.open('POST', `/api/file-manager/domains/${domainId}/upload`)
      xhr.setRequestHeader('Authorization', `Bearer ${localStorage.getItem('token') || this.token}`)

      if (onProgress) {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
        })
      }

      xhr.onload = () => {
        const ct = xhr.getResponseHeader('content-type') || ''
        let data = null
        if (ct.includes('application/json')) {
          try { data = JSON.parse(xhr.responseText) } catch { /* ignore */ }
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data)
        } else {
          const msg = Array.isArray(data?.detail)
            ? data.detail.map(e => `${e.loc?.slice(-1)[0] ?? ''}: ${e.msg}`).join(' | ')
            : data?.detail || `Error ${xhr.status}`
          reject(new Error(msg))
        }
      }

      xhr.onerror = () => reject(new Error('Error de red durante la subida'))
      xhr.onabort = () => reject(new Error('Subida cancelada'))
      xhr.send(formData)
    })
  }

  extractDomainZip(domainId, path, dest = '') {
    return this.post(`/api/file-manager/domains/${domainId}/extract`, { path, dest })
  }

  chmodDomainEntry(domainId, path, mode) {
    return this.post(`/api/file-manager/domains/${domainId}/chmod`, { path, mode })
  }

  async downloadDomainFile(domainId, path) {
    const response = await fetch(
      `/api/file-manager/domains/${domainId}/download?path=${encodeURIComponent(path)}`,
      { headers: this.getHeaders() }
    )
    if (!response.ok) {
      throw new Error(`Error ${response.status}`)
    }
    return response.blob()
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

  // DNS
  getDnsZones() {
    return this.get('/api/dns')
  }

  createDnsZone(data) {
    return this.post('/api/dns', data)
  }

  getDnsZone(zoneId) {
    return this.get(`/api/dns/${zoneId}`)
  }

  updateDnsZone(zoneId, data) {
    return this.put(`/api/dns/${zoneId}`, data)
  }

  deleteDnsZone(zoneId) {
    return this.delete(`/api/dns/${zoneId}`)
  }

  regenerateDnsZone(zoneId) {
    return this.post(`/api/dns/${zoneId}/regenerate`, {})
  }

  getDnsRecords(zoneId) {
    return this.get(`/api/dns/${zoneId}/records`)
  }

  addDnsRecord(zoneId, data) {
    return this.post(`/api/dns/${zoneId}/records`, data)
  }

  updateDnsRecord(zoneId, recordId, data) {
    return this.put(`/api/dns/${zoneId}/records/${recordId}`, data)
  }

  deleteDnsRecord(zoneId, recordId) {
    return this.delete(`/api/dns/${zoneId}/records/${recordId}`)
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

  // System
  getSystemStats() {
    return this.get('/api/system/stats')
  }

  getSystemServices() {
    return this.get('/api/system/services')
  }

  controlService(serviceName, action) {
    return this.post(`/api/system/services/${serviceName}/${action}`, {})
  }

  getServiceConfigs(serviceName) {
    return this.get(`/api/system/services/${serviceName}/configs`)
  }

  readServiceConfig(serviceName, fileLabel) {
    return this.get(`/api/system/services/${serviceName}/config/${encodeURIComponent(fileLabel)}`)
  }

  writeServiceConfig(serviceName, fileLabel, content) {
    return this.put(`/api/system/services/${serviceName}/config/${encodeURIComponent(fileLabel)}`, { content })
  }

  // Mail — dominios de correo
  getMailDomains() {
    return this.get('/api/mail/domains')
  }

  createMailDomain(data) {
    return this.post('/api/mail/domains', data)
  }

  getMailDomain(domainId) {
    return this.get(`/api/mail/domains/${domainId}`)
  }

  updateMailDomain(domainId, data) {
    return this.put(`/api/mail/domains/${domainId}`, data)
  }

  deleteMailDomain(domainId) {
    return this.delete(`/api/mail/domains/${domainId}`)
  }

  // Mail — DKIM
  generateDkim(domainId, selector = 'mail') {
    return this.post(`/api/mail/domains/${domainId}/dkim`, { selector })
  }

  getDkimInfo(domainId) {
    return this.get(`/api/mail/domains/${domainId}/dkim`)
  }

  deleteDkim(domainId) {
    return this.delete(`/api/mail/domains/${domainId}/dkim`)
  }

  // Mail — buzones
  getMailboxes(domainId) {
    return this.get(`/api/mail/domains/${domainId}/mailboxes`)
  }

  createMailbox(domainId, data) {
    return this.post(`/api/mail/domains/${domainId}/mailboxes`, data)
  }

  updateMailbox(domainId, mailboxId, data) {
    return this.put(`/api/mail/domains/${domainId}/mailboxes/${mailboxId}`, data)
  }

  deleteMailbox(domainId, mailboxId) {
    return this.delete(`/api/mail/domains/${domainId}/mailboxes/${mailboxId}`)
  }

  // Mail — alias
  getMailAliases(domainId) {
    return this.get(`/api/mail/domains/${domainId}/aliases`)
  }

  createMailAlias(domainId, data) {
    return this.post(`/api/mail/domains/${domainId}/aliases`, data)
  }

  deleteMailAlias(domainId, aliasId) {
    return this.delete(`/api/mail/domains/${domainId}/aliases/${aliasId}`)
  }

  // Roundcube Webmail — autologin
  /**
   * Consulta si Roundcube está instalado y devuelve su URL.
   * @returns {{ enabled: boolean, url: string|null }}
   */
  getRoundcubeStatus() {
    return this.get('/api/mail/roundcube/status')
  }

  /**
   * Genera un token de autologin de un solo uso (TTL 60s) para el buzón dado.
   * El resultado incluye la URL completa con el token lista para abrir en nueva pestaña.
   * @param {number} domainId
   * @param {number} mailboxId
   * @returns {{ token: string, url: string, expires_in: number }}
   */
  getWebmailToken(domainId, mailboxId) {
    return this.post(
      `/api/mail/domains/${domainId}/mailboxes/${mailboxId}/webmail-token`,
      {}
    )
  }

  // ─── Seguridad (Fase 12) ────────────────────────────────────────────────

  // Firewall
  getFirewallStatus() { return this.get('/api/firewall/status') }
  getFirewallRules(onlyActive = false) {
    return this.get(`/api/firewall/rules${onlyActive ? '?only_active=true' : ''}`)
  }
  createFirewallRule(data)        { return this.post('/api/firewall/rules', data) }
  updateFirewallRule(id, data)    { return this.put(`/api/firewall/rules/${id}`, data) }
  deleteFirewallRule(id)          { return this.delete(`/api/firewall/rules/${id}`) }
  applyFirewallRules()            { return this.post('/api/firewall/apply', {}) }

  // Fail2ban
  getFail2banStatus()             { return this.get('/api/fail2ban/status') }
  getFail2banJails()              { return this.get('/api/fail2ban/jails') }
  toggleFail2banJail(jail, enabled) {
    return this.post(`/api/fail2ban/jails/${jail}/toggle?enabled=${enabled}`, {})
  }
  getBannedIps()                  { return this.get('/api/fail2ban/banned') }
  unbanIp(ip, jail = null)        { return this.post('/api/fail2ban/unban', { ip, jail }) }
  manualBanIp(data)               { return this.post('/api/fail2ban/ban', data) }
  getFail2banWhitelist()          { return this.get('/api/fail2ban/whitelist') }
  addFail2banWhitelist(ip)        { return this.post('/api/fail2ban/whitelist', { ip }) }
  removeFail2banWhitelist(ip)     {
    return this.delete(`/api/fail2ban/whitelist/${encodeURIComponent(ip)}`)
  }

  // IP Lists
  getIpLists()                    { return this.get('/api/firewall/ip-lists') }
  createIpList(data)              { return this.post('/api/firewall/ip-lists', data) }
  updateIpList(id, data)          { return this.put(`/api/firewall/ip-lists/${id}`, data) }
  deleteIpList(id)                { return this.delete(`/api/firewall/ip-lists/${id}`) }
  refreshIpList(id)               { return this.post(`/api/firewall/ip-lists/${id}/refresh`, {}) }
  previewIpList(id, limit = 50)   {
    return this.get(`/api/firewall/ip-lists/${id}/preview?limit=${limit}`)
  }

  // Security monitor
  getSecurityAudit(category = null, limit = 100) {
    let url = `/api/security/audit?limit=${limit}`
    if (category) url += `&category=${encodeURIComponent(category)}`
    return this.get(url)
  }
  getActiveConnections(listening = false) {
    return this.get(`/api/security/connections${listening ? '?listening=true' : ''}`)
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
