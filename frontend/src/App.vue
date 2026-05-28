<template>
  <div class="d-flex h-100">
    <!-- Solo mostrar layout si está autenticado -->
    <template v-if="isAuthenticated">
      <!-- Sidebar -->
      <nav class="sidebar" style="width: 250px;">
        <div class="p-3 border-bottom">
          <h5 class="mb-0">
            <i class="bi bi-server"></i> SVQPanel
          </h5>
        </div>
        <ul class="sidebar-nav">
          <li>
            <router-link to="/dashboard" :class="{active: route.path === '/dashboard'}">
              <i class="bi bi-speedometer2"></i> Dashboard
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/users" :class="{active: route.path === '/users'}">
              <i class="bi bi-people"></i> Usuarios
            </router-link>
          </li>
          <li v-if="['admin','reseller'].includes(currentUser?.role)">
            <router-link to="/plans" :class="{active: route.path === '/plans'}">
              <i class="bi bi-stack"></i> Planes
            </router-link>
          </li>
          <li>
            <router-link to="/domains" :class="{active: route.path === '/domains'}">
              <i class="bi bi-globe"></i> Dominios
            </router-link>
          </li>
          <li>
            <router-link to="/files" :class="{active: route.path === '/files'}">
              <i class="bi bi-folder2-open"></i> Archivos
            </router-link>
          </li>
          <li v-if="currentUser?.role !== 'admin'">
            <router-link to="/sftp" :class="{active: route.path === '/sftp'}">
              <i class="bi bi-folder-symlink"></i> Acceso SFTP
            </router-link>
          </li>
          <li>
            <router-link to="/databases" :class="{active: route.path === '/databases'}">
              <i class="bi bi-database"></i> Bases de Datos
            </router-link>
          </li>
          <li>
            <router-link to="/dns" :class="{active: route.path === '/dns'}">
              <i class="bi bi-diagram-3"></i> DNS
            </router-link>
          </li>
          <li>
            <router-link to="/mail" :class="{active: route.path === '/mail'}">
              <i class="bi bi-envelope"></i> Correo
            </router-link>
          </li>
          <li>
            <router-link to="/crons" :class="{active: route.path === '/crons'}">
              <i class="bi bi-clock-history"></i> Tareas Cron
            </router-link>
          </li>
          <li>
            <router-link to="/backups" :class="{active: route.path === '/backups'}">
              <i class="bi bi-hdd-stack"></i> Copias de seguridad
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/system" :class="{active: route.path === '/system'}">
              <i class="bi bi-hdd-rack"></i> Sistema
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/security" :class="{active: route.path === '/security'}">
              <i class="bi bi-shield-lock"></i> Seguridad
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/server-ips" :class="{active: route.path === '/server-ips'}">
              <i class="bi bi-hdd-network"></i> Gestión de IPs
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/system/updates" :class="{active: route.path === '/system/updates'}">
              <i class="bi bi-arrow-repeat"></i> Actualizaciones
            </router-link>
          </li>
          <li v-if="currentUser?.is_admin">
            <router-link to="/settings" :class="{active: route.path === '/settings'}">
              <i class="bi bi-gear"></i> Configuración
            </router-link>
          </li>
        </ul>
      </nav>

      <!-- Main Content -->
      <div style="flex: 1; overflow-y: auto;">
        <!-- Navbar -->
        <nav class="navbar">
          <div class="container-fluid d-flex justify-content-between">
            <span class="navbar-brand text-white">
              <i class="bi bi-server"></i> SVQPanel v0.1.0
            </span>
            <div class="navbar-user">
              <!-- Campana de notificaciones -->
              <div class="notif-dropdown" v-if="currentUser" @mouseenter="notifOpen=true" @mouseleave="notifOpen=false">
                <button class="btn btn-sm btn-outline-light position-relative me-2" @click="openNotifs">
                  <i class="bi bi-bell"></i>
                  <span v-if="unreadCount > 0"
                        class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">
                    {{ unreadCount > 99 ? '99+' : unreadCount }}
                  </span>
                </button>
                <div class="notif-menu" v-show="notifOpen">
                  <div class="notif-header d-flex justify-content-between align-items-center">
                    <span class="fw-semibold">Notificaciones</span>
                    <button v-if="unreadCount > 0" class="btn btn-link btn-sm p-0 text-decoration-none"
                            @click="markAllRead">Marcar todas leídas</button>
                  </div>
                  <div v-if="!notifs.length" class="notif-empty text-muted">
                    No tienes notificaciones.
                  </div>
                  <div v-else class="notif-list">
                    <div v-for="n in notifs" :key="n.id"
                         class="notif-item" :class="{unread: !n.is_read}"
                         @click="markRead(n)">
                      <div class="d-flex align-items-start gap-2">
                        <i class="bi" :class="iconFor(n.level)"></i>
                        <div class="flex-grow-1">
                          <div class="notif-title">{{ n.title }}</div>
                          <div class="notif-msg">{{ n.message }}</div>
                          <div class="notif-time">{{ formatTime(n.created_at) }}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Dropdown usuario -->
              <div class="user-dropdown" v-if="currentUser" @mouseenter="dropdownOpen=true" @mouseleave="dropdownOpen=false">
                <button class="btn btn-sm btn-outline-light user-dropdown-trigger">
                  <i class="bi bi-person-circle me-1"></i>
                  {{ currentUser.username }}
                  <i class="bi bi-chevron-down ms-1" style="font-size:.7rem"></i>
                </button>
                <div class="user-dropdown-menu" v-show="dropdownOpen">
                  <router-link :to="`/users/${currentUser.id}/account`" class="dropdown-item" @click="dropdownOpen=false">
                    <i class="bi bi-person me-2"></i> Mi cuenta
                  </router-link>
                  <router-link :to="`/users/${currentUser.id}/account`" class="dropdown-item" @click="dropdownOpen=false">
                    <i class="bi bi-shield-lock me-2"></i> Doble factor (2FA)
                  </router-link>
                  <div class="dropdown-divider"></div>
                  <button class="dropdown-item text-danger" @click="logout">
                    <i class="bi bi-box-arrow-right me-2"></i> Cerrar sesión
                  </button>
                </div>
              </div>
            </div>
          </div>
        </nav>

        <!-- Content -->
        <div class="main-content">
          <router-view></router-view>
        </div>
      </div>
    </template>

    <!-- Si no está autenticado, solo mostrar router-view (Login) -->
    <router-view v-else></router-view>

    <!-- Toast Notifications -->
    <div class="alert-toast">
      <div v-if="notification" :class="['alert', `alert-${notification.type}`]" role="alert">
        {{ notification.message }}
      </div>
    </div>
  </div>
</template>

<script>
import { useRoute, useRouter } from 'vue-router'
import { useMainStore } from './stores/useMainStore'
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import api from './services/api'

export default {
  name: 'App',
  setup() {
    const route = useRoute()
    const router = useRouter()
    const store = useMainStore()
    const notification = computed(() => store.notification)
    const isAuthenticated = computed(() => store.isAuthenticated)
    const currentUser = computed(() => store.currentUser)

    const handleLogout = async () => {
      try {
        await api.logout()
      } catch (error) {
        console.error('Error en logout:', error)
      }

      store.logout()
      store.showNotification('Sesión cerrada correctamente', 'success')
      await router.push('/login')
    }

    const dropdownOpen = ref(false)

    const logout = async () => {
      dropdownOpen.value = false
      await handleLogout()
    }

    // ─── Notificaciones ───────────────────────────────────────────────
    const notifOpen    = ref(false)
    const notifs       = ref([])
    const unreadCount  = ref(0)
    let   pollTimer    = null

    const loadUnread = async () => {
      if (!store.isAuthenticated) return
      try {
        const r = await api.getUnreadCount()
        unreadCount.value = r?.unread || 0
      } catch { /* silencioso */ }
    }

    const openNotifs = async () => {
      try {
        notifs.value = await api.getNotifications(false)
      } catch { notifs.value = [] }
    }

    const markRead = async (n) => {
      if (n.is_read) return
      try {
        await api.markNotificationRead(n.id)
        n.is_read = true
        unreadCount.value = Math.max(0, unreadCount.value - 1)
      } catch { /* silencioso */ }
    }

    const markAllRead = async () => {
      try {
        await api.markAllNotificationsRead()
        notifs.value.forEach(n => { n.is_read = true })
        unreadCount.value = 0
      } catch { /* silencioso */ }
    }

    const iconFor = (level) => ({
      danger:  'bi-exclamation-octagon-fill text-danger',
      warning: 'bi-exclamation-triangle-fill text-warning',
      info:    'bi-info-circle-fill text-primary',
    }[level] || 'bi-info-circle-fill text-primary')

    const formatTime = (iso) => {
      if (!iso) return ''
      const d = new Date(iso)
      return d.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    }

    // Poll del contador cada 60s; arranca/para según autenticación
    watch(isAuthenticated, (val) => {
      if (val) {
        loadUnread()
        if (!pollTimer) pollTimer = setInterval(loadUnread, 60000)
      } else {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        unreadCount.value = 0
        notifs.value = []
      }
    }, { immediate: true })

    onMounted(loadUnread)
    onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

    return {
      route,
      notification,
      isAuthenticated,
      currentUser,
      handleLogout,
      logout,
      dropdownOpen,
      notifOpen, notifs, unreadCount,
      openNotifs, markRead, markAllRead, iconFor, formatTime,
    }
  }
}
</script>

<style scoped>
.h-100 {
  height: 100vh;
}

.navbar-user {
  display: flex;
  align-items: center;
}

.btn-outline-light:hover {
  background-color: rgba(255, 255, 255, 0.1);
  border-color: white;
}

/* Dropdown usuario */
.user-dropdown {
  position: relative;
}

.user-dropdown-trigger {
  display: flex;
  align-items: center;
}

.user-dropdown-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,.15);
  min-width: 190px;
  z-index: 9999;
  padding: 4px 0;
}

.user-dropdown-menu .dropdown-item {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  color: #333;
  text-decoration: none;
  font-size: .9rem;
  cursor: pointer;
  background: none;
  border: none;
  width: 100%;
  text-align: left;
  transition: background .15s;
}

.user-dropdown-menu .dropdown-item:hover {
  background: #f0f4ff;
  color: #4a6cf7;
}

.user-dropdown-menu .dropdown-item.text-danger:hover {
  background: #fff0f0;
  color: #dc3545;
}

.user-dropdown-menu .dropdown-divider {
  margin: 4px 0;
  border-top: 1px solid #dee2e6;
}

/* Campana de notificaciones */
.notif-dropdown {
  position: relative;
  display: inline-block;
}

.notif-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,.15);
  width: 340px;
  max-height: 420px;
  overflow: hidden;
  z-index: 9999;
  display: flex;
  flex-direction: column;
}

.notif-header {
  padding: 10px 14px;
  border-bottom: 1px solid #eee;
  color: #333;
  font-size: .9rem;
}

.notif-empty {
  padding: 24px 14px;
  text-align: center;
  font-size: .85rem;
}

.notif-list {
  overflow-y: auto;
}

.notif-item {
  padding: 10px 14px;
  border-bottom: 1px solid #f2f2f2;
  cursor: pointer;
  transition: background .15s;
}

.notif-item:hover {
  background: #f7f9ff;
}

.notif-item.unread {
  background: #eef3ff;
}

.notif-item.unread:hover {
  background: #e3ebff;
}

.notif-title {
  font-weight: 600;
  font-size: .85rem;
  color: #222;
}

.notif-msg {
  font-size: .8rem;
  color: #555;
  margin-top: 2px;
}

.notif-time {
  font-size: .72rem;
  color: #999;
  margin-top: 4px;
}
</style>
