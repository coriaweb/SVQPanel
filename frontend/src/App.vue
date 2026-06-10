<template>
  <div class="app-shell" v-if="isAuthenticated" :data-collapsed="sidebarCollapsed" :class="{ 'mobile-open': mobileMenuOpen }">
    <!-- ===== Sidebar SVQ ===== -->
    <aside class="sb" :class="{ 'sb--collapsed': sidebarCollapsed, 'sb--mobile-open': mobileMenuOpen }">

      <!-- Wordmark -->
      <div class="sb-brand">
        <span class="sb-brand__wordmark">
          SVQ<span class="sb-brand__accent">{{ sidebarCollapsed ? '' : 'Panel' }}</span>
        </span>
        <button class="sb-brand__toggle" @click="store.toggleSidebar()"
          :title="sidebarCollapsed ? 'Expandir menú' : 'Colapsar menú'">
          <i class="bi" :class="sidebarCollapsed ? 'bi-chevron-right' : 'bi-chevron-left'"></i>
        </button>
      </div>

      <!-- Nav -->
      <nav class="sb-nav sb-scroll">
        <div v-for="group in visibleGroups" :key="group.label" class="sb-group">
          <!-- Separador colapsado / etiqueta expandido -->
          <div class="sb-sep" v-if="sidebarCollapsed"></div>
          <p class="sb-group-label" v-else>{{ group.label }}</p>

          <a v-for="item in group.items" :key="item.to"
            :href="item.to"
            class="sb-item"
            :class="{ 'sb-item--active': isActive(item.to) }"
            :title="sidebarCollapsed ? item.label : ''"
            @click.prevent="navigate(item.to)">
            <i class="bi" :class="item.icon"></i>
            <span class="sb-item__label">{{ item.label }}</span>
            <span v-if="item.badge != null && !sidebarCollapsed" class="sb-badge">{{ item.badge }}</span>
          </a>
        </div>
      </nav>

      <!-- Footer: estado del nodo + tema -->
      <div class="sb-footer">
        <div class="sb-node" v-if="!sidebarCollapsed">
          <span class="sb-node__dot"></span>
          <span class="sb-node__text">{{ serverHostname }} · <span class="sb-node__status">operativo</span></span>
        </div>
        <div class="sb-node sb-node--collapsed" v-else>
          <span class="sb-node__dot"></span>
        </div>
        <button class="sb-theme-btn" @click="store.toggleTheme()"
          :title="theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'">
          <i class="bi" :class="theme === 'dark' ? 'bi-sun' : 'bi-moon-stars'"></i>
          <span v-if="!sidebarCollapsed">{{ theme === 'dark' ? 'Modo claro' : 'Modo oscuro' }}</span>
        </button>
      </div>
    </aside>

    <!-- ===== Main ===== -->
    <div class="app-main">

      <!-- Topbar -->
      <header class="topbar">
        <div class="topbar-left">
          <button class="tb-icon-btn" @click="store.toggleSidebar()" title="Menú">
            <i class="bi bi-list"></i>
          </button>
          <!-- Breadcrumb -->
          <nav class="tb-crumb">
            <span class="tb-crumb__sep"><i class="bi bi-chevron-right"></i></span>
            <span class="tb-crumb__group">{{ currentBreadcrumb.group }}</span>
            <span class="tb-crumb__sep"><i class="bi bi-chevron-right"></i></span>
            <span class="tb-crumb__page">{{ currentBreadcrumb.label }}</span>
          </nav>
        </div>

        <div class="topbar-right">
          <!-- Server Load (estilo cPanel: 1/5/15 min) -->
          <div v-if="serverLoad" class="tb-load" :class="`tb-load--${loadLevel}`"
               :title="`Carga del servidor (1 / 5 / 15 min) · ${cpuCount} CPUs`">
            <i class="bi bi-speedometer2"></i>
            <span class="tb-load__label">Load</span>
            <span class="tb-load__vals">
              <b>{{ serverLoad.load_1.toFixed(2) }}</b>
              <span>{{ serverLoad.load_5.toFixed(2) }}</span>
              <span>{{ serverLoad.load_15.toFixed(2) }}</span>
            </span>
          </div>

          <!-- Búsqueda -->
          <button class="tb-search" @click="openPalette" title="Buscar (Ctrl+K)">
            <i class="bi bi-search"></i>
            <span class="tb-search__hint">Buscar en el panel…</span>
            <kbd>/</kbd>
          </button>

          <!-- Notificaciones (placeholder) -->
          <button class="tb-icon-btn tb-icon-btn--rel" title="Notificaciones">
            <i class="bi bi-bell"></i>
          </button>

          <!-- Usuario -->
          <div class="tb-user" @mouseenter="dropdownOpen = true" @mouseleave="dropdownOpen = false">
            <button class="tb-user__btn">
              <span class="tb-avatar">{{ userInitials }}</span>
              <span class="tb-user__name">{{ currentUser?.username }}</span>
              <i class="bi bi-chevron-down tb-user__caret"></i>
            </button>
            <transition name="tb-drop">
              <div class="tb-user__menu" v-show="dropdownOpen">
                <div class="tb-user__head">
                  <span class="tb-avatar tb-avatar--lg">{{ userInitials }}</span>
                  <div>
                    <p class="tb-user__head-name">{{ currentUser?.username }}</p>
                    <p class="tb-user__head-role">{{ currentUser?.is_admin ? 'Administrador' : 'Usuario' }}</p>
                  </div>
                </div>
                <div class="tb-menu-sep"></div>
                <router-link :to="`/users/${currentUser?.id}/account`" class="tb-menu-item" @click="dropdownOpen = false">
                  <i class="bi bi-person"></i> Mi cuenta
                </router-link>
                <button class="tb-menu-item" @click="store.toggleTheme(); dropdownOpen = false">
                  <i class="bi" :class="theme === 'dark' ? 'bi-sun' : 'bi-moon-stars'"></i>
                  {{ theme === 'dark' ? 'Modo claro' : 'Modo oscuro' }}
                </button>
                <div class="tb-menu-sep"></div>
                <button class="tb-menu-item tb-menu-item--danger" @click="logout">
                  <i class="bi bi-box-arrow-right"></i> Cerrar sesión
                </button>
              </div>
            </transition>
          </div>
        </div>
      </header>

      <!-- Backdrop móvil -->
      <div class="app-backdrop" @click="store.closeMobileMenu()"></div>

      <!-- Contenido -->
      <main class="app-content">
        <!-- Aviso de licencia no válida (bloquea operaciones) -->
        <div v-if="licenseBad" class="lic-banner">
          <i class="bi bi-exclamation-octagon-fill lic-banner__icon"></i>
          <div class="lic-banner__text">
            <strong>Licencia no válida o caducada.</strong> El panel está en modo
            limitado: puedes ver tus datos pero no crear ni modificar nada hasta activar
            una licencia.
          </div>
          <router-link to="/license" class="lic-banner__btn">Activar licencia</router-link>
        </div>

        <!-- Aviso de versión beta -->
        <div v-if="showBetaBanner" class="beta-banner">
          <i class="bi bi-cone-striped beta-banner__icon"></i>
          <div class="beta-banner__text">
            <strong>Versión BETA</strong> — Este panel está en desarrollo activo.
            Pueden aparecer errores o cambios. Haz copias de seguridad y reporta cualquier
            problema a <a href="mailto:info@svqhost.com?subject=Reporte%20SVQPanel%20(beta)" class="beta-banner__mail">info@svqhost.com</a>.
          </div>
          <button class="beta-banner__close" @click="dismissBeta" title="Ocultar este aviso">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <router-view></router-view>
      </main>
    </div>

    <!-- Command Palette ⌘K -->
    <CommandPalette />

    <!-- Toast -->
    <div class="toast-stack">
      <transition name="toast">
        <div v-if="notification" class="toast" :class="`toast--${notification.type}`">
          <i class="bi" :class="toastIcon(notification.type)"></i>
          <span>{{ notification.message }}</span>
        </div>
      </transition>
    </div>
  </div>

  <!-- Sin autenticar: login u otras rutas públicas -->
  <router-view v-else></router-view>
</template>

<script>
import { useRoute, useRouter } from 'vue-router'
import { useMainStore } from './stores/useMainStore'
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import api from './services/api'
import CommandPalette from './components/ui/CommandPalette.vue'

export default {
  name: 'App',
  components: { CommandPalette },
  setup() {
    const route  = useRoute()
    const router = useRouter()
    const store  = useMainStore()

    const notification    = computed(() => store.notification)
    const isAuthenticated = computed(() => store.isAuthenticated)
    const currentUser     = computed(() => store.currentUser)
    const theme           = computed(() => store.theme)
    const sidebarCollapsed = computed(() => store.sidebarCollapsed)
    const mobileMenuOpen  = computed(() => store.mobileMenuOpen)
    const dropdownOpen    = ref(false)

    // Aviso de versión beta (se puede ocultar; recuerda la elección en el navegador)
    const showBetaBanner = ref(localStorage.getItem('svq_beta_dismissed') !== '1')
    const dismissBeta = () => {
      localStorage.setItem('svq_beta_dismissed', '1')
      showBetaBanner.value = false
    }

    // Aviso de licencia no válida (banda persistente, no se puede ocultar)
    const licenseBad = ref(false)
    const checkLicense = async () => {
      if (!store.isAuthenticated || store.currentUser?.role !== 'admin') return
      try {
        const st = await api.getLicenseStatus()
        licenseBad.value = !st.valid
      } catch (e) { /* silencioso: no bloquear la UI por esto */ }
    }

    // Navegar y cerrar el drawer móvil
    const navigate = (to) => {
      router.push(to)
      store.closeMobileMenu()
    }

    // ── Hostname del servidor (mostrado en footer del sidebar) ──
    const serverHostname = computed(() => {
      return store.serverHostname || window.location.hostname || 'SVQ-PROD-01'
    })

    // ── Navegación agrupada ──
    const navGroups = [
      {
        label: 'General',
        items: [
          { to: '/dashboard', label: 'Inicio',     icon: 'bi-speedometer2' },
          { to: '/domains',   label: 'Dominios',   icon: 'bi-globe2' },
          { to: '/databases', label: 'Bases de datos', icon: 'bi-database' },
          { to: '/mail',      label: 'Correo',     icon: 'bi-envelope' },
          { to: '/dns',       label: 'DNS',        icon: 'bi-diagram-3' },
        ],
      },
      {
        label: 'Archivos',
        items: [
          { to: '/files',   label: 'Gestor de archivos', icon: 'bi-folder2-open' },
          { to: '/sftp',    label: 'Acceso SFTP',        icon: 'bi-folder-symlink', roles: ['notAdmin'] },
          { to: '/crons',   label: 'Cron Jobs',          icon: 'bi-clock-history' },
          { to: '/backups', label: 'Copias de seguridad',icon: 'bi-hdd-stack' },
        ],
      },
      {
        label: 'Administración',
        items: [
          { to: '/users',      label: 'Usuarios', icon: 'bi-people',      roles: ['admin'] },
          { to: '/plans',      label: 'Planes',   icon: 'bi-stack',       roles: ['admin', 'reseller'] },
          { to: '/server-ips', label: 'IPs',      icon: 'bi-hdd-network', roles: ['admin'] },
          { to: '/db-tuner',   label: 'Optimizar BD', icon: 'bi-speedometer', roles: ['admin'] },
          { to: '/migrations', label: 'Migrar / Importar', icon: 'bi-box-arrow-in-down', roles: ['admin'] },
        ],
      },
      {
        label: 'Sistema',
        items: [
          { to: '/system',         label: 'Servicios',       icon: 'bi-hdd-rack',     roles: ['admin'] },
          { to: '/monitoring',     label: 'Monitorización',  icon: 'bi-graph-up',     roles: ['admin'] },
          { to: '/logs',           label: 'Logs',            icon: 'bi-card-text',    roles: ['admin'] },
          { to: '/security',       label: 'Seguridad',       icon: 'bi-shield-lock',  roles: ['admin'] },
          { to: '/terminal',       label: 'Terminal web',    icon: 'bi-terminal' },
          { to: '/api-tokens',     label: 'API Tokens',      icon: 'bi-key' },
          { to: '/system/updates', label: 'Actualizaciones', icon: 'bi-arrow-repeat', roles: ['admin'] },
          { to: '/license',        label: 'Licencia',        icon: 'bi-patch-check',  roles: ['admin'] },
          { to: '/settings',       label: 'Configuración',   icon: 'bi-gear',         roles: ['admin'] },
        ],
      },
    ]

    const canSee = (item) => {
      if (!item.roles) return true
      const u = currentUser.value || {}
      return item.roles.some((r) => {
        if (r === 'admin')    return u.is_admin
        if (r === 'notAdmin') return !u.is_admin
        return u.role === r
      })
    }

    const visibleGroups = computed(() =>
      navGroups.map((g) => ({ ...g, items: g.items.filter(canSee) })).filter((g) => g.items.length > 0)
    )

    // Lista de todas las rutas del menú, para detectar la coincidencia más específica
    const allNavPaths = navGroups.flatMap((g) => g.items.map((it) => it.to))

    const isActive = (to) => {
      if (route.path === to) return true
      if (to === '/dashboard') return false
      // ¿La ruta actual cuelga de "to"? (p. ej. /domains/1 bajo /domains)
      if (!route.path.startsWith(to + '/')) return false
      // Si existe otra ruta del menú más específica que también encaja
      // (p. ej. /system/updates cuando "to" es /system), entonces "to" NO
      // debe marcarse activo: gana el item más concreto.
      const moreSpecific = allNavPaths.some(
        (p) => p !== to && p.length > to.length &&
               (route.path === p || route.path.startsWith(p + '/')) &&
               p.startsWith(to + '/')
      )
      return !moreSpecific
    }

    // ── Breadcrumb ──
    const allItems = navGroups.flatMap((g) => g.items.map((it) => ({ ...it, group: g.label })))
    const currentBreadcrumb = computed(() => {
      const match = allItems
        .filter((it) => isActive(it.to))
        .sort((a, b) => b.to.length - a.to.length)[0]
      return match || { label: 'Panel', group: 'SVQPanel' }
    })

    const userInitials = computed(() => (currentUser.value?.username || '?').slice(0, 2).toUpperCase())

    const toastIcon = (type) => ({
      success: 'bi-check-circle-fill',
      danger:  'bi-exclamation-octagon-fill',
      error:   'bi-exclamation-octagon-fill',
      warning: 'bi-exclamation-triangle-fill',
      info:    'bi-info-circle-fill',
    }[type] || 'bi-info-circle-fill')

    const logout = async () => {
      dropdownOpen.value = false
      try { await api.logout() } catch (e) { /* ignorar */ }
      store.logout()
      store.showNotification('Sesión cerrada correctamente', 'success')
      await router.push('/login')
    }

    const openPalette = () => window.dispatchEvent(new CustomEvent('svq:open-command-palette'))

    // ── Server Load en la topbar (estilo cPanel: 1/5/15 min) ──
    const serverLoad = ref(null)
    const cpuCount = ref(1)
    let loadTimer = null
    const loadServerLoad = async () => {
      if (!store.isAuthenticated || !store.currentUser?.is_admin) return
      try {
        const s = await api.get('/api/system/stats')
        serverLoad.value = { load_1: s.load_1, load_5: s.load_5, load_15: s.load_15 }
        cpuCount.value = s.cpu_count || 1
      } catch (e) { /* silencioso */ }
    }
    // Nivel de color: verde si load_1 < nCPU, naranja si < 1.5×nCPU, rojo si más
    const loadLevel = computed(() => {
      if (!serverLoad.value) return 'ok'
      const r = serverLoad.value.load_1 / Math.max(1, cpuCount.value)
      return r < 0.85 ? 'ok' : r < 1.5 ? 'warn' : 'crit'
    })
    onMounted(() => {
      loadServerLoad()
      loadTimer = setInterval(loadServerLoad, 15000)  // refresco cada 15s
      checkLicense()
    })
    onUnmounted(() => { if (loadTimer) clearInterval(loadTimer) })
    // Cargar al iniciar sesión (cuando cambia la autenticación)
    watch(isAuthenticated, (v) => { if (v) { loadServerLoad(); checkLicense() } })

    return {
      store, route, router, notification, isAuthenticated, currentUser, theme,
      sidebarCollapsed, mobileMenuOpen, navigate, dropdownOpen, visibleGroups, isActive, currentBreadcrumb,
      userInitials, toastIcon, logout, openPalette, serverHostname,
      serverLoad, cpuCount, loadLevel,
      showBetaBanner, dismissBeta, licenseBad,
    }
  },
}
</script>

<style scoped>
/* ══════════════════════════════════════════════════
   Aviso versión BETA
══════════════════════════════════════════════════ */
.beta-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  margin-bottom: 18px;
  border-radius: 12px;
  background: linear-gradient(90deg, rgba(232,89,12,.14), rgba(232,89,12,.06));
  border: 1px solid rgba(232,89,12,.35);
  color: var(--text);
}
.beta-banner__icon { font-size: 1.4rem; color: var(--svq-orange, #e8590c); flex-shrink: 0; }
.beta-banner__text { font-size: .9rem; line-height: 1.4; flex: 1; }
.beta-banner__text strong { color: var(--svq-orange, #e8590c); letter-spacing: .3px; }
.beta-banner__mail { color: var(--svq-orange, #e8590c); font-weight: 600; text-decoration: underline; }
.beta-banner__close {
  background: none; border: none; cursor: pointer; color: var(--text-muted);
  font-size: 1rem; padding: 4px; border-radius: 6px; flex-shrink: 0;
}
.beta-banner__close:hover { background: rgba(0,0,0,.08); color: var(--text); }

/* Aviso de licencia no válida (rojo, no se puede ocultar) */
.lic-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  margin-bottom: 18px;
  border-radius: 12px;
  background: linear-gradient(90deg, rgba(220,38,38,.16), rgba(220,38,38,.06));
  border: 1px solid rgba(220,38,38,.45);
  color: var(--text);
}
.lic-banner__icon { font-size: 1.4rem; color: #dc2626; flex-shrink: 0; }
.lic-banner__text { font-size: .9rem; line-height: 1.4; flex: 1; }
.lic-banner__text strong { color: #dc2626; }
.lic-banner__btn {
  flex-shrink: 0; background: #dc2626; color: #fff; text-decoration: none;
  padding: 7px 14px; border-radius: 8px; font-weight: 600; font-size: .85rem;
}
.lic-banner__btn:hover { background: #b91c1c; }

/* ══════════════════════════════════════════════════
   Shell
══════════════════════════════════════════════════ */
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}
.app-main {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.app-content {
  flex: 1; overflow-y: auto;
  padding: 20px 24px;
  background: var(--bg);
}

/* ══════════════════════════════════════════════════
   Sidebar
══════════════════════════════════════════════════ */
.sb {
  width: 260px; flex-shrink: 0;
  background: var(--sb-bg);
  color: var(--sb-text);
  display: flex; flex-direction: column;
  height: 100vh; position: sticky; top: 0;
  transition: width .22s ease;
  overflow: hidden;
}
.sb--collapsed { width: 72px; }

/* Scrollbar fino */
.sb-scroll::-webkit-scrollbar { width: 5px; }
.sb-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,.12); border-radius: 10px; }
.sb-scroll::-webkit-scrollbar-track { background: transparent; }

/* Wordmark */
.sb-brand {
  min-height: 66px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--sb-border);
  flex-shrink: 0;
}
.sb--collapsed .sb-brand { justify-content: center; padding: 0; }
.sb-brand__wordmark {
  font-size: 20px; font-weight: 800; letter-spacing: -.01em;
  color: #fff; white-space: nowrap;
}
.sb-brand__accent { color: var(--svq-orange); }
.sb-brand__toggle {
  width: 28px; height: 28px; border: none; background: transparent;
  color: var(--sb-muted); border-radius: 4px; cursor: pointer;
  display: grid; place-items: center; font-size: 14px;
  transition: background .15s, color .15s; flex-shrink: 0;
}
.sb-brand__toggle:hover { background: var(--sb-hover); color: #fff; }
.sb--collapsed .sb-brand__toggle { display: none; }

/* Nav */
.sb-nav { flex: 1; overflow-y: auto; overflow-x: hidden; padding-bottom: 8px; }
.sb-group-label {
  margin: 0; padding: 14px 22px 5px;
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .1em; color: var(--sb-muted);
}
.sb-sep { height: 1px; background: var(--sb-border); margin: 8px 14px; }

/* Items */
.sb-item {
  display: flex; align-items: center; gap: 11px;
  padding: 10px 22px; text-decoration: none;
  font-size: 13.5px; font-weight: 400;
  color: var(--sb-text);
  border-left: 3px solid transparent;
  transition: background .15s, color .15s;
  position: relative; white-space: nowrap;
}
.sb-item .bi { font-size: 18px; flex-shrink: 0; }
.sb-item__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.sb-item:hover { background: var(--sb-hover); }
.sb-item--active {
  color: var(--svq-orange) !important;
  font-weight: 600;
  background: var(--sb-active-bg);
  border-left-color: var(--svq-orange);
}
.sb--collapsed .sb-item { padding: 11px 0; justify-content: center; }
.sb--collapsed .sb-item__label { display: none; }
.sb--collapsed .sb-item--active { border-left-color: transparent; border-right: 3px solid var(--svq-orange); }

.sb-badge {
  margin-left: auto; font-size: 11px; font-weight: 600;
  color: var(--sb-muted); background: rgba(255,255,255,.08);
  border-radius: 50rem; padding: 1px 8px;
}

/* Footer */
.sb-footer {
  padding: 10px 14px;
  border-top: 1px solid var(--sb-border);
  display: flex; flex-direction: column; gap: 4px;
  flex-shrink: 0;
}
.sb--collapsed .sb-footer { align-items: center; padding: 12px 0; }

.sb-node {
  display: flex; align-items: center; gap: 9px;
  font-size: 12px; color: var(--sb-muted); padding: 4px 8px;
}
.sb-node--collapsed { justify-content: center; padding: 0; }
.sb-node__dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: var(--success); flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(11,179,131,.18);
}
.sb-node__status { color: rgba(255,255,255,.85); }

.sb-theme-btn {
  display: flex; align-items: center; gap: 11px;
  width: 100%; padding: 9px 8px;
  border: none; background: transparent; cursor: pointer;
  color: var(--sb-muted); font-size: 13px; font-family: var(--font-sans);
  border-radius: 4px; text-align: left;
  transition: background .15s, color .15s;
}
.sb-theme-btn:hover { background: var(--sb-hover); color: var(--sb-text); }
.sb-theme-btn .bi { font-size: 17px; }
.sb--collapsed .sb-theme-btn { justify-content: center; padding: 9px 0; }
.sb--collapsed .sb-theme-btn span { display: none; }

/* ══════════════════════════════════════════════════
   Topbar
══════════════════════════════════════════════════ */
.topbar {
  height: 66px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 100;
}
.topbar-left, .topbar-right { display: flex; align-items: center; gap: 12px; }

/* Server Load (estilo cPanel) */
.tb-load {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 11px; border-radius: var(--r-md);
  background: var(--surface-inset); border: 1px solid var(--border);
  font-size: 12.5px; color: var(--text-secondary);
}
.tb-load > .bi { font-size: 15px; }
.tb-load__label { font-weight: 600; text-transform: uppercase; letter-spacing: .03em; font-size: 11px; }
.tb-load__vals { display: flex; gap: 7px; font-family: var(--font-mono); }
.tb-load__vals b { color: var(--text); font-weight: 700; }
.tb-load__vals span { opacity: .65; }
.tb-load--ok   > .bi { color: var(--success); }
.tb-load--warn > .bi { color: var(--warning, #d97706); }
.tb-load--warn { border-color: color-mix(in srgb, var(--warning, #d97706) 40%, transparent); }
.tb-load--crit > .bi { color: var(--danger); }
.tb-load--crit { border-color: color-mix(in srgb, var(--danger) 45%, transparent); }
.tb-load--crit .tb-load__vals b { color: var(--danger); }
@media (max-width: 720px) { .tb-load__label { display: none; } }
@media (max-width: 560px) { .tb-load { display: none; } }

.tb-icon-btn {
  width: 38px; height: 38px; border: none; background: transparent;
  color: var(--text-secondary); border-radius: var(--r-md); cursor: pointer;
  display: grid; place-items: center; font-size: 20px;
  transition: background .15s;
}
.tb-icon-btn:hover { background: var(--surface-inset); color: var(--text); }
.tb-icon-btn--rel { position: relative; }

.tb-crumb {
  display: flex; align-items: center; gap: 7px;
  font-size: 13px; color: var(--text-muted);
}
.tb-crumb__sep { font-size: 16px; opacity: .5; }
.tb-crumb__group { color: var(--text-muted); }
.tb-crumb__page  { color: var(--svq-navy); font-weight: 600; }
[data-theme="dark"] .tb-crumb__page { color: var(--text); }

.tb-search {
  display: flex; align-items: center; gap: 9px;
  padding: 7px 13px;
  background: var(--surface-inset); border: 1px solid var(--border);
  border-radius: var(--r-md); color: var(--text-muted);
  font-size: 13px; cursor: pointer; font-family: var(--font-sans);
  transition: background .15s, border-color .15s; min-width: 220px;
}
.tb-search:hover { background: var(--surface); border-color: var(--border-strong); }
.tb-search__hint { flex: 1; text-align: left; }
.tb-search kbd {
  font-size: 10px; font-weight: 600; color: var(--text-muted);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 3px; padding: 1px 5px; font-family: var(--font-sans);
}

/* Usuario */
.tb-user { position: relative; }
.tb-user__btn {
  display: flex; align-items: center; gap: 9px;
  padding: 5px 10px 5px 5px;
  border: 1px solid var(--border); background: var(--surface);
  border-radius: 50rem; cursor: pointer; color: var(--text);
  font-family: var(--font-sans); font-size: 13px; font-weight: 500;
  transition: background .15s, border-color .15s;
}
.tb-user__btn:hover { background: var(--surface-inset); border-color: var(--border-strong); }
.tb-user__name { font-weight: 600; color: var(--svq-navy); }
[data-theme="dark"] .tb-user__name { color: var(--text); }
.tb-user__caret { font-size: 11px; color: var(--text-muted); }

.tb-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--svq-navy); color: #fff;
  font-size: 11px; font-weight: 700; flex-shrink: 0;
}
.tb-avatar--lg { width: 38px; height: 38px; font-size: 13px; }

.tb-user__menu {
  position: absolute; right: 0; top: calc(100% + 8px);
  min-width: 240px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-lg); box-shadow: var(--shadow-lg);
  padding: 4px; z-index: 1000; overflow: hidden;
}
.tb-user__head {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 14px 10px;
}
.tb-user__head-name { margin: 0; font-weight: 600; color: var(--text); font-size: 14px; }
.tb-user__head-role { margin: 0; font-size: 12px; color: var(--text-muted); text-transform: capitalize; }
.tb-menu-sep { height: 1px; background: var(--border); margin: 3px 0; }
.tb-menu-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 9px 14px;
  border: none; background: transparent; cursor: pointer;
  color: var(--text-secondary); text-decoration: none;
  font-size: 13.5px; border-radius: var(--r-md);
  text-align: left; font-family: var(--font-sans);
  transition: background .15s, color .15s;
}
.tb-menu-item:hover { background: var(--surface-inset); color: var(--text); }
.tb-menu-item--danger { color: var(--danger); }
.tb-menu-item--danger:hover { background: var(--danger-bg); color: var(--danger); }

.tb-drop-enter-active, .tb-drop-leave-active { transition: opacity .15s ease, transform .15s ease; }
.tb-drop-enter-from, .tb-drop-leave-to { opacity: 0; transform: translateY(-6px); }

/* ══════════════════════════════════════════════════
   Toast
══════════════════════════════════════════════════ */
.toast-stack { position: fixed; bottom: 24px; right: 24px; z-index: 9999; }
@media (max-width: 600px) {
  .toast-stack { left: 12px; right: 12px; bottom: 12px; }
  .toast { min-width: 0; max-width: 100%; }
}
.toast {
  display: flex; align-items: center; gap: 12px;
  min-width: 280px; max-width: 420px;
  padding: 13px 16px;
  background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--text-muted);
  border-radius: var(--r-md); box-shadow: var(--shadow-lg);
  color: var(--text); font-size: 14px;
}
.toast .bi { font-size: 18px; }
.toast--success { border-left-color: var(--success); } .toast--success .bi { color: var(--success); }
.toast--danger, .toast--error { border-left-color: var(--danger); } .toast--danger .bi, .toast--error .bi { color: var(--danger); }
.toast--warning { border-left-color: var(--warning); } .toast--warning .bi { color: var(--warning); }
.toast--info    { border-left-color: var(--info); }    .toast--info .bi    { color: var(--info); }
.toast-enter-active, .toast-leave-active { transition: opacity .2s ease, transform .2s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(16px); }

/* ══════════════════════════════════════════════════
   Backdrop móvil
══════════════════════════════════════════════════ */
.app-backdrop { display: none; }

/* ══════════════════════════════════════════════════
   Responsive
══════════════════════════════════════════════════ */
@media (max-width: 768px) {
  /* El sidebar es un drawer: oculto por defecto, se desliza al abrir el menú */
  .sb {
    position: fixed; top: 0; bottom: 0; left: 0; z-index: 1100;
    transform: translateX(-100%); width: 264px !important;
    box-shadow: var(--shadow-lg); transition: transform .24s ease;
  }
  .sb--mobile-open { transform: translateX(0); }
  /* En el drawer siempre se muestran las etiquetas (nunca colapsado) */
  .sb.sb--collapsed { width: 264px !important; }
  .sb.sb--collapsed .sb-item { padding: 10px 22px; justify-content: flex-start; }
  .sb.sb--collapsed .sb-item__label { display: block; }
  .sb.sb--collapsed .sb-brand__accent::after { content: 'Panel'; }
  .sb.sb--collapsed .sb-theme-btn span { display: inline; }

  .app-content { padding: 14px 16px; }
  .tb-search { display: none; }
  .tb-user__name { display: none; }
  .tb-crumb { display: none; }
  .topbar { padding: 0 14px; }

  .app-backdrop {
    display: block; position: fixed; inset: 0; z-index: 1050;
    background: rgba(0,0,0,.45); opacity: 0; pointer-events: none;
    transition: opacity .24s ease;
  }
  .mobile-open .app-backdrop { opacity: 1; pointer-events: auto; }
}

@media (max-width: 480px) {
  .app-content { padding: 12px 12px; }
  .topbar { height: 58px; }
}
</style>
