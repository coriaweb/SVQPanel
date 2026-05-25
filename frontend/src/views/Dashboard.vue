<template>
  <div>
    <h2 class="mb-4">
      <i class="bi bi-speedometer2"></i> Dashboard
      <small class="text-muted fs-6 ms-2">Bienvenido, {{ currentUser?.username }}</small>
    </h2>

    <!-- Stats Grid -->
    <div class="row g-3 mb-4">
      <div v-if="isAdminOrReseller" class="col-6 col-md-3">
        <div class="card text-center p-3">
          <i class="bi bi-people fs-1 text-primary mb-2"></i>
          <h3 class="mb-0">{{ totalUsers }}</h3>
          <p class="text-muted mb-0 small">{{ isReseller ? 'Mis clientes' : 'Usuarios' }}</p>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card text-center p-3">
          <i class="bi bi-globe fs-1 text-success mb-2"></i>
          <h3 class="mb-0">{{ totalDomains }}</h3>
          <p class="text-muted mb-0 small">Dominios</p>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card text-center p-3">
          <i class="bi bi-shield-lock fs-1 text-warning mb-2"></i>
          <h3 class="mb-0">{{ totalSSL }}</h3>
          <p class="text-muted mb-0 small">SSL activos</p>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card text-center p-3">
          <i class="bi bi-person-badge fs-1 text-info mb-2"></i>
          <span class="badge fs-6" :class="roleBadgeClass">{{ roleLabel }}</span>
          <p class="text-muted mb-0 small mt-1">Tu rol</p>
        </div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="card mb-4">
      <div class="card-header">
        <i class="bi bi-lightning-fill me-1"></i> Acciones rápidas
      </div>
      <div class="card-body d-flex gap-2 flex-wrap">
        <router-link v-if="isAdminOrReseller" to="/users" class="btn btn-outline-primary">
          <i class="bi bi-person-plus me-1"></i>
          {{ isReseller ? 'Mis clientes' : 'Gestionar usuarios' }}
        </router-link>
        <router-link to="/domains" class="btn btn-outline-success">
          <i class="bi bi-globe2 me-1"></i> Mis dominios
        </router-link>
        <router-link v-if="isAdmin" to="/settings" class="btn btn-outline-secondary">
          <i class="bi bi-gear me-1"></i> Configuración
        </router-link>
      </div>
    </div>

    <!-- Dominios recientes -->
    <div class="card">
      <div class="card-header">
        <i class="bi bi-clock-history me-1"></i> Dominios recientes
      </div>
      <div class="card-body">
        <div v-if="loadingDomains" class="text-center py-3">
          <div class="spinner-border spinner-border-sm"></div>
        </div>
        <div v-else-if="recentDomains.length === 0" class="text-muted">
          No hay dominios todavía.
        </div>
        <ul v-else class="list-group list-group-flush">
          <li v-for="d in recentDomains" :key="d.id" class="list-group-item d-flex justify-content-between align-items-center">
            <span><i class="bi bi-globe text-primary me-2"></i>{{ d.domain_name }}</span>
            <span class="badge bg-info text-dark">PHP {{ d.php_version || '8.2' }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'Dashboard',
  setup() {
    const store = useMainStore()
    const currentUser = computed(() => store.currentUser)
    const isAdmin = computed(() => currentUser.value?.role === 'admin' || currentUser.value?.is_admin)
    const isReseller = computed(() => currentUser.value?.role === 'reseller')
    const isAdminOrReseller = computed(() => isAdmin.value || isReseller.value)

    const roleLabel = computed(() => {
      switch (currentUser.value?.role) {
        case 'admin': return '🔑 Administrador'
        case 'reseller': return '🏪 Reseller'
        default: return '👤 Usuario'
      }
    })
    const roleBadgeClass = computed(() => {
      switch (currentUser.value?.role) {
        case 'admin': return 'badge bg-danger'
        case 'reseller': return 'badge bg-warning text-dark'
        default: return 'badge bg-secondary'
      }
    })

    const totalUsers = ref(0)
    const totalDomains = ref(0)
    const totalSSL = ref(0)
    const recentDomains = ref([])
    const loadingDomains = ref(true)

    onMounted(async () => {
      // Cargar dominios — disponible para todos
      try {
        loadingDomains.value = true
        const domains = await api.getDomains(null, 0, 100)
        const list = Array.isArray(domains) ? domains : []
        totalDomains.value = list.length
        totalSSL.value = list.filter(d => d.ssl_enabled).length
        recentDomains.value = list.slice(0, 5)
      } catch (e) {
        // silencioso — puede que no haya dominios
      } finally {
        loadingDomains.value = false
      }

      // Cargar usuarios — solo admin/reseller
      if (isAdminOrReseller.value) {
        try {
          const users = await api.getUsers(0, 100)
          totalUsers.value = Array.isArray(users) ? users.length : 0
        } catch (e) {
          // silencioso
        }
      }
    })

    return {
      currentUser,
      isAdmin,
      isReseller,
      isAdminOrReseller,
      roleLabel,
      roleBadgeClass,
      totalUsers,
      totalDomains,
      totalSSL,
      recentDomains,
      loadingDomains,
    }
  }
}
</script>
