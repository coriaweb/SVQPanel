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
              <span class="text-white me-3">
                <i class="bi bi-person-circle"></i> {{ currentUser?.username || 'Usuario' }}
              </span>
              <button class="btn btn-sm btn-outline-light" @click="handleLogout">
                <i class="bi bi-box-arrow-right"></i> Salir
              </button>
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
import { computed } from 'vue'
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

    return {
      route,
      notification,
      isAuthenticated,
      currentUser,
      handleLogout
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
</style>
