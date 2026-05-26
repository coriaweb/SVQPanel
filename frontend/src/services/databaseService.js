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

  // Listar charsets y collations disponibles
  async getCharsets() {
    const data = await api.get('/api/databases/charsets')
    return data?.charsets || []
  },

  // Obtener URL de acceso phpMyAdmin (autologin, token de un solo uso)
  async getPMAToken(dbId) {
    return api.get(`/api/databases/${dbId}/pma-token`)
  }
}
