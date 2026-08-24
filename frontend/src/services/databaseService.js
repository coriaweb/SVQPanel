import api from './api'

export default {
  // Listar BDs del usuario (o de un usuario específico si es admin/reseller)
  async list(userId = null, skip = 0, limit = 50) {
    const params = new URLSearchParams()
    params.append('skip', skip)
    params.append('limit', limit)
    if (userId) params.append('user_id', userId)

    return api.get(`/api/databases?${params.toString()}`)
  },

  // Obtener detalle de una BD
  async getDetail(dbId) {
    return api.get(`/api/databases/${dbId}`)
  },

  // Crear BD
  async create(data) {
    return api.post('/api/databases', data)
  },

  // Actualizar BD (quota, dominio, estado)
  async update(dbId, data) {
    return api.put(`/api/databases/${dbId}`, data)
  },

  // Cambiar contraseña
  async resetPassword(dbId, newPassword) {
    return api.put(`/api/databases/${dbId}/password`, {
      new_password: newPassword
    })
  },

  // Eliminar BD
  async delete(dbId) {
    return api.delete(`/api/databases/${dbId}`)
  },

  // Listar usuarios adicionales de una BD
  async listDbUsers(dbId) {
    return api.get(`/api/databases/${dbId}/users`)
  },

  // Crear usuario adicional
  async createDbUser(dbId, data) {
    return api.post(`/api/databases/${dbId}/users`, data)
  },

  // Actualizar permisos y/o contraseña de usuario adicional
  async updateDbUser(dbId, userId, data) {
    return api.put(`/api/databases/${dbId}/users/${userId}`, data)
  },

  // Eliminar usuario adicional
  async deleteDbUser(dbId, userId) {
    return api.delete(`/api/databases/${dbId}/users/${userId}`)
  },

  // Listar charsets y collations disponibles
  async getCharsets() {
    const data = await api.get('/api/databases/charsets')
    return data?.charsets || []
  },

  // Obtener URL de acceso phpMyAdmin (autologin, token de un solo uso)
  async getPMAToken(dbId) {
    return api.get(`/api/databases/${dbId}/pma-token`)
  },

  // Descargar volcado .sql.gz de la BD (llega en streaming, sin fichero temporal
  // en el servidor). Devuelve { blob, filename } igual que downloadDomainSite.
  async exportDump(dbId) {
    const response = await fetch(`/api/databases/${dbId}/export`, {
      headers: api.getHeaders()
    })
    if (!response.ok) {
      let msg = `Error ${response.status}`
      try {
        const data = await response.json()
        msg = data?.message || data?.detail || msg
      } catch { /* respuesta no-JSON */ }
      throw new Error(msg)
    }
    const cd = response.headers.get('content-disposition') || ''
    const m = /filename="?([^"]+)"?/.exec(cd)
    const filename = m ? m[1] : `bd_${dbId}.sql.gz`
    const blob = await response.blob()
    return { blob, filename }
  },

  // ── Acceso remoto (allowlist de IPs por BD) ──
  async listRemoteHosts(dbId) {
    return api.get(`/api/databases/${dbId}/remote-hosts`)
  },
  async addRemoteHost(dbId, ip) {
    return api.post(`/api/databases/${dbId}/remote-hosts`, { ip })
  },
  async removeRemoteHost(dbId, ip) {
    return api.delete(`/api/databases/${dbId}/remote-hosts/${encodeURIComponent(ip)}`)
  }
}
