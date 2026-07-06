import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useMainStore = defineStore('main', () => {
  const notification = ref(null)
  const loading = ref(false)
  const users = ref([])
  const domains = ref([])
  const currentUser = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const token = ref(localStorage.getItem('token') || null)
  const isAuthenticated = ref(!!token.value)
  const theme = ref(localStorage.getItem('theme') || 'light')
  const sidebarCollapsed = ref(localStorage.getItem('sidebarCollapsed') === '1')
  const mobileMenuOpen = ref(false)
  const branding = ref(null)   // marca blanca (null = marca SVQPanel por defecto)

  const applyTheme = (value) => {
    theme.value = value
    document.documentElement.dataset.theme = value
    localStorage.setItem('theme', value)
  }

  const toggleTheme = () => {
    applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  const toggleSidebar = () => {
    // En móvil (≤768px) el botón controla la apertura del drawer;
    // en desktop controla el colapso del sidebar.
    if (window.innerWidth <= 768) {
      mobileMenuOpen.value = !mobileMenuOpen.value
    } else {
      sidebarCollapsed.value = !sidebarCollapsed.value
      localStorage.setItem('sidebarCollapsed', sidebarCollapsed.value ? '1' : '0')
    }
  }

  const closeMobileMenu = () => { mobileMenuOpen.value = false }

  // ── Marca blanca ──────────────────────────────────────────────────────
  // Mezcla dos colores hex (t=0 → a, t=1 → b) para derivar tonos del acento
  const _mixHex = (a, b, t) => {
    const pa = a.match(/\w\w/g).map(x => parseInt(x, 16))
    const pb = b.match(/\w\w/g).map(x => parseInt(x, 16))
    return '#' + pa.map((v, i) =>
      Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, '0')).join('')
  }
  const _rgba = (hex, alpha) => {
    const [r, g, b] = hex.match(/\w\w/g).map(x => parseInt(x, 16))
    return `rgba(${r},${g},${b},${alpha})`
  }

  const applyBranding = (b) => {
    branding.value = b && b.is_custom ? b : null
    const root = document.documentElement
    const accentVars = ['--svq-orange', '--ac', '--ac-soft', '--ac-link',
      '--color-primary', '--color-primary-hover', '--shadow-focus',
      '--brand-50', '--brand-400']

    if (branding.value?.accent_color) {
      const c = branding.value.accent_color
      root.style.setProperty('--svq-orange', c)
      root.style.setProperty('--ac', c)
      root.style.setProperty('--ac-soft', _rgba(c, 0.13))
      root.style.setProperty('--ac-link', _mixHex(c, '#000000', 0.18))
      root.style.setProperty('--color-primary', c)
      root.style.setProperty('--color-primary-hover', _mixHex(c, '#000000', 0.12))
      root.style.setProperty('--shadow-focus', `0 0 0 3px ${_rgba(c, 0.28)}`)
      root.style.setProperty('--brand-50', _mixHex(c, '#ffffff', 0.9))
      root.style.setProperty('--brand-400', _mixHex(c, '#ffffff', 0.25))
    } else {
      accentVars.forEach(v => root.style.removeProperty(v))
    }

    // Título de la pestaña
    document.title = branding.value
      ? branding.value.panel_name
      : 'SVQPanel - Web Server Control Panel'

    // Favicon personalizado (se quita si se restaura la marca por defecto)
    const existing = document.querySelector('link[rel="icon"][data-brand]')
    if (branding.value?.has_favicon) {
      const link = existing || document.createElement('link')
      link.rel = 'icon'
      link.dataset.brand = '1'
      link.href = `/api/branding/favicon?v=${encodeURIComponent(branding.value.version || '0')}`
      if (!existing) document.head.appendChild(link)
    } else if (existing) {
      existing.remove()
    }
  }

  const loadBranding = async () => {
    try {
      const r = await fetch('/api/branding')
      if (r.ok) applyBranding(await r.json())
    } catch { /* sin respuesta: se queda la marca por defecto */ }
  }

  let notifTimer = null
  // Duración del toast. Los errores duran mucho más (hay que poder leerlos y
  // copiarlos: pueden traer instrucciones largas). duration = 0 → no se cierra
  // solo (sticky); el usuario lo cierra con la ×. Si no se pasa duration, se
  // elige según el tipo: éxito/info corto, error largo.
  const showNotification = (message, type = 'success', duration = null) => {
    if (notifTimer) { clearTimeout(notifTimer); notifTimer = null }
    // 'danger' y 'error' son ambos errores en el panel; duran mucho más.
    const isError = (type === 'error' || type === 'danger')
    if (duration === null) duration = isError ? 12000 : 3000
    notification.value = { message, type }
    if (duration > 0) {
      notifTimer = setTimeout(() => { notification.value = null }, duration)
    }
  }

  const dismissNotification = () => {
    if (notifTimer) { clearTimeout(notifTimer); notifTimer = null }
    notification.value = null
  }

  const setLoading = (state) => {
    loading.value = state
  }

  const updateUsers = (data) => {
    users.value = data
  }

  const updateDomains = (data) => {
    domains.value = data
  }

  const setCurrentUser = (user) => {
    currentUser.value = user
    if (user) {
      localStorage.setItem('user', JSON.stringify(user))
    }
  }

  const setToken = (newToken) => {
    token.value = newToken
    isAuthenticated.value = !!newToken
    if (newToken) {
      localStorage.setItem('token', newToken)
    } else {
      localStorage.removeItem('token')
    }
  }

  const logout = () => {
    token.value = null
    isAuthenticated.value = false
    currentUser.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  return {
    notification,
    loading,
    users,
    domains,
    currentUser,
    token,
    isAuthenticated,
    theme,
    sidebarCollapsed,
    mobileMenuOpen,
    branding,
    applyBranding,
    loadBranding,
    applyTheme,
    toggleTheme,
    toggleSidebar,
    closeMobileMenu,
    showNotification,
    dismissNotification,
    setLoading,
    updateUsers,
    updateDomains,
    setCurrentUser,
    setToken,
    logout
  }
})
