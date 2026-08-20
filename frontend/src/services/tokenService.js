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

  // Editar un token existente: nombre, caducidad y allowlist de IPs.
  // El secreto NO cambia: los clientes que ya lo usan siguen funcionando.
  // data = { name?, expires_at?: string|null, allowed_ips?: string[] }
  // Ojo: enviar allowed_ips: [] o expires_at: null QUITA la restricción;
  // omitir el campo la deja como estaba.
  async update(tokenId, data) {
    return api.put(`/api/tokens/${tokenId}`, data)
  },

  // Revocar (desactivar) un token. Irreversible.
  async revoke(tokenId) {
    return api.delete(`/api/tokens/${tokenId}`)
  },
}
