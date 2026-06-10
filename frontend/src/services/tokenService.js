import api from './api'

// Gestión de API tokens (acceso programático a la API del panel).
export default {
  // Listar tokens (los del usuario; admin puede pasar userId para filtrar)
  async list(userId = null) {
    const qs = userId ? `?user_id=${userId}` : ''
    return api.get(`/api/tokens${qs}`)
  },

  // Crear token. Devuelve el secreto en claro UNA sola vez (campo `secret`).
  // data = { name, expires_at?, allowed_ips?: string[] }
  async create(data) {
    return api.post('/api/tokens', data)
  },

  // Revocar (desactivar) un token. Irreversible.
  async revoke(tokenId) {
    return api.delete(`/api/tokens/${tokenId}`)
  },
}
