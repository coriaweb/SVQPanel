<template>
  <div class="app-shell" v-if="isAuthenticated">
    <!-- ===== Sidebar ===== -->
    <aside class="sidebar" :class="{ 'is-collapsed': sidebarCollapsed }">
      <div class="sidebar__brand">
        <div class="brand-mark"><i class="bi bi-hexagon-fill"></i></div>
        <span class="brand-name" v-if="!sidebarCollapsed">SVQPanel</span>
        <button class="sidebar__toggle" @click="store.toggleSidebar()" :title="sidebarCollapsed ? 'Expandir' : 'Colapsar'">
          <i class="bi" :class="sidebarCollapsed ? 'bi-chevron-right' : 'bi-chevron-left'"></i>
        </button>
      </div>

      <nav class="sidebar__nav">
        <div class="nav-group" v-for="group in visibleGroups" :key="group.label">
          <p class="nav-group__label" v-if="!sidebarCollapsed">{{ group.label }}</p>
          <div class="nav-group__sep" v-else></div>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item.to) }"
            :title="sidebarCollapsed ? item.label : ''"
          >
            <i class="bi" :class="item.icon"></i>
            <span class="nav-item__label" v-if="!sidebarCollapsed">{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar__footer">
        <button class="nav-item nav-item--btn" @click="store.toggleTheme()" :title="sidebarCollapsed ? 'Cambiar tema' : ''">
          <i class="bi" :class="theme === 'dark' ? 'bi-sun' : 'bi-moon-stars'"></i>
          <span class="nav-item__label" v-if="!sidebarCollapsed">{{ theme === 'dark' ? 'Modo claro' : 'Modo oscuro' }}</span>
        </button>
      </div>
    </aside>

    <!-- ===== Main ===== -->
    <div class="app-main">
      <header class="topbar">
        <div class="topbar__left">
          <button class="icon-btn topbar__menu" @click="store.toggleSidebar()" title="Menú">
            <i class="bi bi-list"></i>
          </button>
          <nav class="breadcrumb">
            <i class="bi bi-house-door breadcrumb__home"></i>
            <span class="breadcrumb__crumb" v-for="(crumb, i) in breadcrumbs" :key="i">
              <span class="breadcrumb__sep">/</span>
              <span class="breadcrumb__item" :class="{ 'is-current': i === breadcrumbs.length - 1 }">{{ crumb }}</span>
            </span>
          </nav>
        </div>

        <div class="topbar__right">
          <button class="search-trigger" @click="openPalette" title="Búsqueda global (Ctrl/⌘ + K)">
            <i class="bi bi-search"></i>
            <span class="search-trigger__hint">Buscar</span>
            <kbd>⌘K</kbd>
          </button>

          <div class="user-menu" @mouseenter="dropdownOpen = true" @mouseleave="dropdownOpen = false">
            <button class="user-menu__trigger">
              <span class="avatar">{{ userInitials }}</span>
              <span class="user-menu__name">{{ currentUser?.username }}</span>
              <i class="bi bi-chevron-down"></i>
            </button>
            <transition name="dropdown">
              <div class="user-menu__panel" v-show="dropdownOpen">
                <div class="user-menu__head">
                  <span class="avatar avatar--lg">{{ userInitials }}</span>
                  <div>
                    <p class="user-menu__head-name">{{ currentUser?.username }}</p>
                    <p class="user-menu__head-role">{{ currentUser?.role || (currentUser?.is_admin ? 'admin' : 'usuario') }}</p>
                  </div>
                </div>
                <router-link :to="`/users/${currentUser.id}/account`" class="dropdown-item" @click="dropdownOpen = false">
                  <i class="bi bi-person"></i> Mi cuenta
                </router-link>
                <router-link :to="`/users/${currentUser.id}/account`" class="dropdown-item" @click="dropdownOpen = false">
                  <i class="bi bi-shield-lock"></i> Doble factor (2FA)
                </router-link>
                <button class="dropdown-item" @click="store.toggleTheme()">
                  <i class="bi" :class="theme === 'dark' ? 'bi-sun' : 'bi-moon-stars'"></i>
                  {{ theme === 'dark' ? 'Modo claro' : 'Modo oscuro' }}
                </button>
                <div class="dropdown-sep"></div>
                <button class="dropdown-item dropdown-item--danger" @click="logout">
                  <i class="bi bi-box-arrow-right"></i> Cerrar sesión
                </button>
              </div>
            </transition>
          </div>
        </div>
      </header>

      <!-- Backdrop móvil cuando el sidebar está abierto -->
      <div class="app-backdrop" @click="store.toggleSidebar()"></div>

      <main class="app-content">
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

  <!-- Sin autenticar -->
  <router-view v-else></router-view>
</template>

<script>
import { useRoute, useRouter } from 'vue-router'
import { useMainStore } from './stores/useMainStore'
import { computed, ref } from 'vue'
import api from './services/api'
import CommandPalette from './components/ui/CommandPalette.vue'

export default {
  name: 'App',
  components: { CommandPalette },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const store = useMainStore()

    const notification = computed(() => store.notification)
    const isAuthenticated = computed(() => store.isAuthenticated)
    const currentUser = computed(() => store.currentUser)
    const theme = computed(() => store.theme)
    const sidebarCollapsed = computed(() => store.sidebarCollapsed)
    const dropdownOpen = ref(false)

    // ===== Definición de navegación agrupada =====
    const navGroups = [
      {
        label: 'Hosting',
        items: [
          { to: '/dashboard', label: 'Dashboard',      icon: 'bi-speedometer2' },
          { to: '/domains',   label: 'Dominios',        icon: 'bi-globe2' },
          { to: '/databases', label: 'Bases de datos',  icon: 'bi-database' },
          { to: '/mail',      label: 'Correo',          icon: 'bi-envelope' },
          { to: '/dns',       label: 'DNS',             icon: 'bi-diagram-3' },
        ],
      },
      {
        label: 'Archivos',
        items: [
          { to: '/files',   label: 'Archivos',     icon: 'bi-folder2-open' },
          { to: '/sftp',    label: 'Acceso SFTP',  icon: 'bi-folder-symlink', roles: ['notAdmin'] },
          { to: '/crons',   label: 'Tareas Cron',  icon: 'bi-clock-history' },
          { to: '/backups', label: 'Copias',       icon: 'bi-hdd-stack' },
        ],
      },
      {
        label: 'Administración',
        items: [
          { to: '/users',      label: 'Usuarios',  icon: 'bi-people',       roles: ['admin'] },
          { to: '/plans',      label: 'Planes',    icon: 'bi-stack',        roles: ['admin', 'reseller'] },
          { to: '/server-ips', label: 'IPs',       icon: 'bi-hdd-network',  roles: ['admin'] },
        ],
      },
      {
        label: 'Sistema',
        items: [
          { to: '/system',         label: 'Servicios',       icon: 'bi-hdd-rack',     roles: ['admin'] },
          { to: '/security',       label: 'Seguridad',       icon: 'bi-shield-lock',  roles: ['admin'] },
          { to: '/system/updates', label: 'Actualizaciones', icon: 'bi-arrow-repeat', roles: ['admin'] },
          { to: '/settings',       label: 'Configuración',   icon: 'bi-gear',         roles: ['admin'] },
        ],
      },
    ]

    const canSee = (item) => {
      if (!item.roles) return true
      const u = currentUser.value || {}
      return item.roles.some((r) => {
        if (r === 'admin') return u.is_admin
        if (r === 'notAdmin') return !u.is_admin
        return u.role === r
      })
    }

    const visibleGroups = computed(() =>
      navGroups
        .map((g) => ({ ...g, items: g.items.filter(canSee) }))
        .filter((g) => g.items.length > 0)
    )

    const isActive = (to) => {
      if (to === '/dashboard') return route.path === to
      // Exact match for subroutes
      if (to === '/system/updates' || to === '/security') return route.path === to
      // For parent routes, check exact boundary
      if (route.path === to) return true
      if (route.path.startsWith(to + '/')) return true
      return false
    }

    // ===== Breadcrumbs =====
    const titleByPath = {}
    navGroups.forEach((g) => g.items.forEach((it) => { titleByPath[it.to] = it.label }))
    const breadcrumbs = computed(() => {
      const match = Object.keys(titleByPath)
        .filter((p) => isActive(p))
        .sort((a, b) => b.length - a.length)[0]
      return match ? [titleByPath[match]] : [route.name || 'Inicio']
    })

    const userInitials = computed(() => {
      const n = currentUser.value?.username || '?'
      return n.slice(0, 2).toUpperCase()
    })

    const toastIcon = (type) => ({
      success: 'bi-check-circle-fill',
      danger:  'bi-exclamation-octagon-fill',
      error:   'bi-exclamation-octagon-fill',
      warning: 'bi-exclamation-triangle-fill',
      info:    'bi-info-circle-fill',
    }[type] || 'bi-info-circle-fill')

    const logout = async () => {
      dropdownOpen.value = false
      try { await api.logout() } catch (e) { console.error('Error en logout:', e) }
      store.logout()
      store.showNotification('Sesión cerrada correctamente', 'success')
      await router.push('/login')
    }

    const openPalette = () => window.dispatchEvent(new CustomEvent('svq:open-command-palette'))

    return {
      store, route, notification, isAuthenticated, currentUser, theme,
      sidebarCollapsed, dropdownOpen, visibleGroups, isActive, breadcrumbs,
      userInitials, toastIcon, logout, openPalette,
    }
  },
}
</script>

<style scoped>
/* ===================== Shell ===================== */
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.app-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-6);
}

/* ===================== Sidebar ===================== */
.sidebar {
  width: var(--sidebar-w);
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width var(--t-base) var(--ease);
}
.sidebar.is-collapsed { width: var(--sidebar-w-collapsed); }

.sidebar__brand {
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-4);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.brand-mark {
  width: 32px; height: 32px;
  display: grid; place-items: center;
  border-radius: var(--r-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-size: 16px;
  flex-shrink: 0;
}
.brand-name {
  font-weight: var(--fw-bold);
  font-size: var(--fs-md);
  letter-spacing: -.01em;
  color: var(--text);
}
.sidebar__toggle {
  margin-left: auto;
  width: 26px; height: 26px;
  border: none; background: transparent;
  color: var(--text-muted);
  border-radius: var(--r-sm);
  cursor: pointer;
  display: grid; place-items: center;
  transition: background var(--t-fast), color var(--t-fast);
}
.sidebar__toggle:hover { background: var(--surface-inset); color: var(--text); }
.sidebar.is-collapsed .sidebar__toggle {
  position: absolute; right: -13px; top: 50%; transform: translateY(-50%);
  background: var(--surface); border: 1px solid var(--border);
  box-shadow: var(--shadow-sm); z-index: 5;
}

.sidebar__nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-3) var(--sp-3);
}
.nav-group__label {
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  margin: var(--sp-4) var(--sp-3) var(--sp-2);
}
.nav-group__sep { height: 1px; background: var(--border); margin: var(--sp-3) var(--sp-2); }

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 9px var(--sp-3);
  margin: 2px 0;
  border-radius: var(--r-md);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  position: relative;
  transition: background var(--t-fast), color var(--t-fast);
  white-space: nowrap;
}
.nav-item .bi { font-size: 17px; width: 20px; text-align: center; flex-shrink: 0; }
.nav-item:hover { background: var(--surface-inset); color: var(--text); }
.nav-item.active { background: var(--brand-50); color: var(--color-primary); font-weight: var(--fw-semibold); }
[data-theme="dark"] .nav-item.active { background: var(--surface-2); color: var(--brand-400); }
.nav-item.active::before {
  content: ''; position: absolute; left: -1px; top: 8px; bottom: 8px;
  width: 3px; border-radius: var(--r-pill); background: var(--color-primary);
}
.sidebar.is-collapsed .nav-item { justify-content: center; padding: 9px 0; }
.sidebar.is-collapsed .nav-item.active::before { left: 0; top: 6px; bottom: 6px; }

.sidebar__footer { padding: var(--sp-3); border-top: 1px solid var(--border); }
.nav-item--btn { width: 100%; border: none; background: transparent; cursor: pointer; text-align: left; }

/* ===================== Topbar ===================== */
.topbar {
  height: var(--topbar-h);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-6);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.topbar__left, .topbar__right { display: flex; align-items: center; gap: var(--sp-3); }
.topbar__menu { display: none; }

.icon-btn {
  width: 36px; height: 36px;
  border: none; background: transparent;
  color: var(--text-secondary);
  border-radius: var(--r-md);
  cursor: pointer; display: grid; place-items: center;
  font-size: 18px;
  transition: background var(--t-fast);
}
.icon-btn:hover { background: var(--surface-inset); color: var(--text); }

.breadcrumb { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-base); }
.breadcrumb__crumb { display: flex; align-items: center; gap: var(--sp-2); }
.breadcrumb__home { color: var(--text-muted); }
.breadcrumb__sep { color: var(--text-muted); }
.breadcrumb__item { color: var(--text-secondary); }
.breadcrumb__item.is-current { color: var(--text); font-weight: var(--fw-semibold); }

.search-trigger {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: 7px var(--sp-3);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: background var(--t-fast), border-color var(--t-fast);
}
.search-trigger:hover { background: var(--surface); border-color: var(--border-strong); }
.search-trigger__hint { min-width: 90px; text-align: left; }
.search-trigger kbd {
  font-family: var(--font-sans); font-size: 11px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 1px 6px; color: var(--text-secondary);
}

/* ===== User menu ===== */
.user-menu { position: relative; }
.user-menu__trigger {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: 5px var(--sp-2) 5px 5px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--r-pill);
  cursor: pointer;
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  transition: background var(--t-fast), border-color var(--t-fast);
}
.user-menu__trigger:hover { background: var(--surface-inset); border-color: var(--border-strong); }
.user-menu__trigger .bi { font-size: 11px; color: var(--text-muted); }
.avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--brand-400), var(--brand-600));
  color: #fff; font-size: 11px; font-weight: var(--fw-bold);
  flex-shrink: 0;
}
.avatar--lg { width: 40px; height: 40px; font-size: 14px; }

.user-menu__panel {
  position: absolute; right: 0; top: calc(100% + 8px);
  min-width: 240px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--sp-2);
  z-index: 1000;
}
.user-menu__head { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3); }
.user-menu__head-name { margin: 0; font-weight: var(--fw-semibold); color: var(--text); }
.user-menu__head-role { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); text-transform: capitalize; }
.dropdown-item {
  display: flex; align-items: center; gap: var(--sp-3);
  width: 100%; padding: 9px var(--sp-3);
  border: none; background: transparent; cursor: pointer;
  color: var(--text-secondary); text-decoration: none;
  font-size: var(--fs-base); border-radius: var(--r-md);
  text-align: left; transition: background var(--t-fast), color var(--t-fast);
}
.dropdown-item .bi { width: 18px; }
.dropdown-item:hover { background: var(--surface-inset); color: var(--text); }
.dropdown-item--danger { color: var(--danger); }
.dropdown-item--danger:hover { background: var(--danger-bg); color: var(--danger); }
.dropdown-sep { height: 1px; background: var(--border); margin: var(--sp-2) 0; }

.dropdown-enter-active, .dropdown-leave-active { transition: opacity var(--t-fast) var(--ease), transform var(--t-fast) var(--ease); }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-6px); }

/* ===================== Toast ===================== */
.toast-stack { position: fixed; bottom: var(--sp-6); right: var(--sp-6); z-index: 9999; }
.toast {
  display: flex; align-items: center; gap: var(--sp-3);
  min-width: 280px; max-width: 400px;
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-muted);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
  color: var(--text);
  font-size: var(--fs-base);
}
.toast .bi { font-size: 18px; }
.toast--success { border-left-color: var(--success); } .toast--success .bi { color: var(--success); }
.toast--danger, .toast--error { border-left-color: var(--danger); } .toast--danger .bi, .toast--error .bi { color: var(--danger); }
.toast--warning { border-left-color: var(--warning); } .toast--warning .bi { color: var(--warning); }
.toast--info { border-left-color: var(--info); } .toast--info .bi { color: var(--info); }
.toast-enter-active, .toast-leave-active { transition: opacity var(--t-base) var(--ease), transform var(--t-base) var(--ease-out); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(20px); }

/* ===================== Backdrop (móvil) ===================== */
.app-backdrop { display: none; }

/* ===================== Responsive ===================== */
@media (max-width: 768px) {
  .sidebar {
    position: fixed; top: 0; bottom: 0; left: 0; z-index: 1100;
    transform: translateX(-100%);
    box-shadow: var(--shadow-lg);
    width: var(--sidebar-w) !important;
  }
  .sidebar:not(.is-collapsed) { transform: translateX(0); }
  .sidebar.is-collapsed { transform: translateX(-100%); }
  .sidebar__toggle { display: none; }
  .topbar__menu { display: grid; }
  .search-trigger__hint, .search-trigger kbd { display: none; }
  .user-menu__name { display: none; }
  .app-content { padding: var(--sp-4); }
  .app-backdrop {
    display: block; position: fixed; inset: 0; z-index: 1050;
    background: rgba(0,0,0,.4); opacity: 0; pointer-events: none;
    transition: opacity var(--t-base);
  }
  .sidebar:not(.is-collapsed) ~ .app-main .app-backdrop { opacity: 1; pointer-events: auto; }
}
</style>
