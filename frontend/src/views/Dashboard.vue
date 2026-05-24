<template>
  <div>
    <h2 class="mb-4">
      <i class="bi bi-speedometer2"></i> Dashboard
    </h2>

    <!-- Stats Grid -->
    <div class="dashboard-grid">
      <div class="stat-card">
        <i class="bi bi-person-fill icon-large"></i>
        <h3>{{ totalUsers }}</h3>
        <p>Usuarios</p>
      </div>
      <div class="stat-card">
        <i class="bi bi-globe icon-large"></i>
        <h3>{{ totalDomains }}</h3>
        <p>Dominios</p>
      </div>
      <div class="stat-card">
        <i class="bi bi-shield-lock icon-large"></i>
        <h3>{{ totalSSL }}</h3>
        <p>Certificados SSL</p>
      </div>
      <div class="stat-card">
        <i class="bi bi-hdd-network icon-large"></i>
        <h3>{{ totalIPv6 }}</h3>
        <p>Direcciones IPv6</p>
      </div>
    </div>

    <!-- Recent Activity -->
    <div class="card">
      <div class="card-header">
        <i class="bi bi-clock-history"></i> Actividad Reciente
      </div>
      <div class="card-body">
        <p class="text-muted">
          Últimas acciones del sistema
        </p>
        <ul class="list-unstyled">
          <li v-for="item in activities" :key="item.id" class="mb-2">
            <small>
              <strong>{{ item.action }}</strong> - {{ item.timestamp }}
            </small>
          </li>
        </ul>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="card">
      <div class="card-header">
        <i class="bi bi-lightning-fill"></i> Acciones Rápidas
      </div>
      <div class="card-body">
        <router-link to="/users" class="btn btn-primary me-2">
          <i class="bi bi-person-plus"></i> Nuevo Usuario
        </router-link>
        <router-link to="/domains" class="btn btn-primary">
          <i class="bi bi-plus-circle"></i> Nuevo Dominio
        </router-link>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'Dashboard',
  setup() {
    const store = useMainStore()
    const totalUsers = ref(0)
    const totalDomains = ref(0)
    const totalSSL = ref(0)
    const totalIPv6 = ref(0)
    const activities = ref([
      { id: 1, action: 'Sistema inicializado', timestamp: new Date().toLocaleString() }
    ])

    onMounted(async () => {
      try {
        const users = await api.getUsers()
        const domains = await api.getDomains()

        totalUsers.value = Array.isArray(users) ? users.length : 0
        totalDomains.value = Array.isArray(domains) ? domains.length : 0

        store.showNotification('Dashboard cargado', 'success')
      } catch (error) {
        store.showNotification('Error al cargar datos', 'danger')
      }
    })

    return {
      totalUsers,
      totalDomains,
      totalSSL,
      totalIPv6,
      activities
    }
  }
}
</script>
