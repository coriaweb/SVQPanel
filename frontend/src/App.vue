<template>
  <div class="d-flex h-100">
    <!-- Sidebar -->
    <nav class="sidebar" style="width: 250px;">
      <div class="p-3 border-bottom">
        <h5 class="mb-0">
          <i class="bi bi-server"></i> SVQPanel
        </h5>
      </div>
      <ul class="sidebar-nav">
        <li>
          <router-link to="/" :class="{active: route.path === '/'}">
            <i class="bi bi-speedometer2"></i> Dashboard
          </router-link>
        </li>
        <li>
          <router-link to="/users" :class="{active: route.path === '/users'}">
            <i class="bi bi-people"></i> Usuarios
          </router-link>
        </li>
        <li>
          <router-link to="/domains" :class="{active: route.path === '/domains'}">
            <i class="bi bi-globe"></i> Dominios
          </router-link>
        </li>
        <li>
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
        <div class="container-fluid">
          <span class="navbar-brand text-white">
            <i class="bi bi-server"></i> SVQPanel v0.1.0
          </span>
          <div class="text-white">
            <i class="bi bi-person-circle"></i> Admin
          </div>
        </div>
      </nav>

      <!-- Content -->
      <div class="main-content">
        <router-view></router-view>
      </div>
    </div>

    <!-- Toast Notifications -->
    <div class="alert-toast">
      <div v-if="notification" :class="['alert', `alert-${notification.type}`]" role="alert">
        {{ notification.message }}
      </div>
    </div>
  </div>
</template>

<script>
import { useRoute } from 'vue-router'
import { useMainStore } from './stores/useMainStore'
import { computed } from 'vue'

export default {
  name: 'App',
  setup() {
    const route = useRoute()
    const store = useMainStore()
    const notification = computed(() => store.notification)

    return {
      route,
      notification
    }
  }
}
</script>

<style scoped>
.h-100 {
  height: 100vh;
}
</style>
