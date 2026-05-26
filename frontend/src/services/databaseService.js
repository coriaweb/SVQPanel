import api from './api'

export default {
  // Listar BDs del usuario (o de un usuario específico si es admin/reseller)
  async list(userId = null, skip = 0, limit = 50) {
    const params = new URLSearchParams()
    params.append('skip', skip)
    params.append('limit', limit)
    if (userId) params.append('user_id', userId)

    const response = await api.get(`/databases?${params.toString()}`)
    return response.data
  },

  // Obtener detalle de una BD
  async getDetail(dbId) {
    const response = await api.get(`/databases/${dbId}`)
    return response.data
  },

  // Crear BD
  async create(data) {
    const response = await api.post('/databases', data)
    return response.data
  },

  // Actualizar BD (quota, dominio, estado)
  async update(dbId, data) {
    const response = await api.put(`/databases/${dbId}`, data)
    return response.data
  },

  // Cambiar contraseña
  async resetPassword(dbId, newPassword) {
    const response = await api.put(`/databases/${dbId}/password`, {
      new_password: newPassword
    })
    return response.data
  },

  // Eliminar BD
  async delete(dbId) {
    const response = await api.delete(`/databases/${dbId}`)
    return response.data
  },

  // Listar charsets y collations disponibles
  async getCharsets() {
    const response = await api.get('/databases/charsets')
    return response.data.charsets || []
  }
}
