<template>
  <div class="dashboard">
    <!-- Cabecera -->
    <header class="page-head">
      <div>
        <h1 class="page-title">Dashboard</h1>
        <p class="page-sub">
          Hola, <strong>{{ currentUser?.username }}</strong>
          <template v-if="stats"> · {{ stats.os_name }} · <StatusBadge status="online" label="online" :pulse="false" /></template>
        </p>
      </div>
      <BaseButton variant="secondary" size="sm" icon="arrow-repeat" :loading="loading" @click="reload">
        Actualizar
      </BaseButton>
    </header>

    <!-- ===== Métricas ===== -->
    <div class="metrics-grid">
      <MetricCard
        icon="globe2" tone="brand"
        label="Dominios" :value="totalDomains"
        :hint="`${activeDomains} activos`" :loading="loadingDomains" />
      <MetricCard
        icon="shield-check" tone="success"
        label="SSL activos" :value="totalSSL"
        :hint="totalDomains ? `${sslPct}% de los dominios` : 'sin dominios'" :loading="loadingDomains" />
      <MetricCard
        v-if="isAdminOrReseller"
        icon="people" tone="info"
        :label="isReseller ? 'Mis clientes' : 'Usuarios'" :value="totalUsers"
        :hint="stats ? `${stats.suspended_users} suspendidos` : ''" :loading="loadingStats" />
      <MetricCard
        v-if="isAdmin"
        icon="hdd-network" tone="warning"
        label="Zonas DNS" :value="stats?.total_dns_zones ?? '—'"
        :hint="stats ? `${stats.total_dns_records} registros` : ''" :loading="loadingStats" />
      <MetricCard
        v-if="!isAdmin"
        icon="diagram-3" tone="warning"
        label="Tu rol" :value="roleShort" hint="Cuenta de hosting" />
    </div>

    <!-- ===== Fila principal ===== -->
    <div class="dash-row">
      <!-- Estado del servidor (solo admin) -->
      <BaseCard v-if="isAdmin" title="Estado del servidor" icon="cpu" class="dash-server">
        <template #actions>
          <StatusBadge :status="loadTone" :label="loadLabel" />
        </template>
        <div class="server-grid">
          <div class="server-gauge">
            <ResourceGauge ring :value="loadPct" caption="carga" />
          </div>
          <div class="server-info">
            <div class="info-row">
              <span class="info-row__k">Tiempo activo</span>
              <span class="info-row__v">{{ stats?.uptime_str || '—' }}</span>
            </div>
            <div class="info-row">
              <span class="info-row__k">Carga (1 / 5 / 15 min)</span>
              <span class="info-row__v mono">{{ stats ? `${stats.load_1} / ${stats.load_5} / ${stats.load_15}` : '—' }}</span>
            </div>
            <div class="info-row">
              <span class="info-row__k">Núcleos CPU</span>
              <span class="info-row__v">{{ stats?.cpu_count ?? '—' }}</span>
            </div>
            <div class="info-row">
              <span class="info-row__k">Sistema operativo</span>
              <span class="info-row__v">{{ stats?.os_name || '—' }}</span>
            </div>
          </div>
        </div>
      </BaseCard>

      <!-- Servicios (solo admin) -->
      <BaseCard v-if="isAdmin" title="Servicios" icon="hdd-stack" flush class="dash-services">
        <template #actions>
          <router-link to="/system" class="link-more">Ver todo <i class="bi bi-arrow-right"></i></router-link>
        </template>
        <div v-if="loadingServices" class="svc-list">
          <div v-for="n in 4" :key="n" class="svc-item">
            <span class="svq-skeleton" style="width:120px;height:14px"></span>
            <span class="svq-skeleton" style="width:60px;height:14px"></span>
          </div>
        </div>
        <EmptyState v-else-if="!topServices.length" icon="hdd-rack" title="Sin servicios detectados" />
        <div v-else class="svc-list">
          <div v-for="svc in topServices" :key="svc.name" class="svc-item">
            <span class="svc-name">
              <StatusBadge :status="svc.is_running ? 'running' : (svc.state === 'failed' ? 'failed' : 'stopped')" :label="''" />
              <span class="mono">{{ svc.name }}</span>
            </span>
            <span class="svc-state">{{ svc.is_running ? 'activo' : svc.state }}</span>
          </div>
        </div>
      </BaseCard>

      <!-- Acciones rápidas (todos) -->
      <BaseCard title="Acciones rápidas" icon="lightning-charge" class="dash-actions">
        <div class="quick-actions">
          <router-link to="/domains" class="quick-action">
            <i class="bi bi-globe2"></i><span>Mis dominios</span>
          </router-link>
          <router-link to="/databases" class="quick-action">
            <i class="bi bi-database"></i><span>Bases de datos</span>
          </router-link>
          <router-link to="/mail" class="quick-action">
            <i class="bi bi-envelope"></i><span>Correo</span>
          </router-link>
          <router-link to="/files" class="quick-action">
            <i class="bi bi-folder2-open"></i><span>Archivos</span>
          </router-link>
          <router-link v-if="isAdminOrReseller" to="/users" class="quick-action">
            <i class="bi bi-person-plus"></i><span>{{ isReseller ? 'Clientes' : 'Usuarios' }}</span>
          </router-link>
          <router-link v-if="isAdmin" to="/security" class="quick-action">
            <i class="bi bi-shield-lock"></i><span>Seguridad</span>
          </router-link>
        </div>
      </BaseCard>
    </div>

    <!-- ===== Dominios recientes ===== -->
    <BaseCard title="Dominios recientes" icon="clock-history" flush>
      <template #actions>
        <router-link to="/domains" class="link-more">Ver todos <i class="bi bi-arrow-right"></i></router-link>
      </template>
      <div v-if="loadingDomains" class="dom-list">
        <div v-for="n in 3" :key="n" class="dom-item">
          <span class="svq-skeleton" style="width:180px;height:16px"></span>
          <span class="svq-skeleton" style="width:70px;height:20px"></span>
        </div>
      </div>
      <EmptyState
        v-else-if="!recentDomains.length"
        icon="globe2"
        title="Aún no tienes dominios"
        description="Crea tu primer dominio para empezar a alojar sitios web.">
        <BaseButton tag="router-link" v-bind="{ to: '/domains' }" variant="primary" icon="plus-lg">Crear dominio</BaseButton>
      </EmptyState>
      <div v-else class="dom-list">
        <router-link v-for="d in recentDomains" :key="d.id" to="/domains" class="dom-item">
          <span class="dom-name"><i class="bi bi-globe2"></i>{{ d.domain_name }}</span>
          <span class="dom-meta">
            <StatusBadge :status="d.ssl_enabled ? 'valid' : 'none'" :label="d.ssl_enabled ? 'SSL' : 'sin SSL'" :icon="d.ssl_enabled ? 'lock-fill' : 'unlock'" :dot="false" />
            <span class="dom-php">PHP {{ d.php_version || '8.2' }}</span>
          </span>
        </router-link>
      </div>
    </BaseCard>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import MetricCard from '../components/ui/MetricCard.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import ResourceGauge from '../components/ui/ResourceGauge.vue'
import EmptyState from '../components/ui/EmptyState.vue'

export default {
  name: 'Dashboard',
  components: { BaseCard, BaseButton, MetricCard, StatusBadge, ResourceGauge, EmptyState },
  setup() {
    const store = useMainStore()
    const currentUser = computed(() => store.currentUser)
    const isAdmin = computed(() => currentUser.value?.role === 'admin' || currentUser.value?.is_admin)
    const isReseller = computed(() => currentUser.value?.role === 'reseller')
    const isAdminOrReseller = computed(() => isAdmin.value || isReseller.value)

    const roleShort = computed(() => ({
      admin: 'Admin', reseller: 'Reseller',
    }[currentUser.value?.role] || 'Usuario'))

    const totalUsers = ref(0)
    const totalDomains = ref(0)
    const activeDomains = ref(0)
    const totalSSL = ref(0)
    const recentDomains = ref([])
    const stats = ref(null)
    const services = ref([])
    const loadingDomains = ref(true)
    const loadingStats = ref(false)
    const loadingServices = ref(false)

    const sslPct = computed(() =>
      totalDomains.value ? Math.round((totalSSL.value / totalDomains.value) * 100) : 0)

    // Carga del sistema = load_1 / cpu_count (métrica estándar, dato real del backend)
    const loadPct = computed(() => {
      if (!stats.value || !stats.value.cpu_count) return 0
      return Math.min(100, Math.round((parseFloat(stats.value.load_1) / stats.value.cpu_count) * 100))
    })
    const loadTone = computed(() => loadPct.value >= 90 ? 'danger' : loadPct.value >= 70 ? 'warning' : 'success')
    const loadLabel = computed(() => loadPct.value >= 90 ? 'sobrecarga' : loadPct.value >= 70 ? 'carga alta' : 'saludable')

    const topServices = computed(() => services.value.slice(0, 6))

    const loadDomains = async () => {
      try {
        loadingDomains.value = true
        const domains = await api.getDomains(null, 0, 100)
        const list = Array.isArray(domains) ? domains : []
        totalDomains.value = list.length
        activeDomains.value = list.filter(d => d.is_active !== false).length
        totalSSL.value = list.filter(d => d.ssl_enabled).length
        recentDomains.value = list.slice(0, 5)
      } catch (e) { /* silencioso */ } finally {
        loadingDomains.value = false
      }
    }

    const loadAdminData = async () => {
      if (!isAdmin.value) {
        if (isReseller.value) {
          try { const u = await api.getUsers(0, 100); totalUsers.value = Array.isArray(u) ? u.length : 0 } catch {}
        }
        return
      }
      loadingStats.value = true
      loadingServices.value = true
      try {
        stats.value = await api.getSystemStats()
        totalUsers.value = stats.value?.total_users ?? 0
      } catch {} finally { loadingStats.value = false }
      try {
        const svc = await api.getSystemServices()
        services.value = Array.isArray(svc) ? svc : (svc?.services || [])
      } catch {} finally { loadingServices.value = false }
    }

    const reload = async () => { await Promise.all([loadDomains(), loadAdminData()]) }

    onMounted(reload)

    return {
      currentUser, isAdmin, isReseller, isAdminOrReseller, roleShort,
      totalUsers, totalDomains, activeDomains, totalSSL, recentDomains,
      stats, topServices, loadingDomains, loadingStats, loadingServices,
      sslPct, loadPct, loadTone, loadLabel, reload,
    }
  },
}
</script>

<style scoped>
.dashboard { max-width: var(--content-max); margin: 0 auto; display: flex; flex-direction: column; gap: var(--sp-6); }

.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--sp-4); }
.page-title { margin: 0; font-size: var(--fs-2xl); font-weight: var(--fw-bold); letter-spacing: -.02em; color: var(--text); }
.page-sub { margin: var(--sp-1) 0 0; color: var(--text-secondary); display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }

.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); }

.dash-row { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: var(--sp-4); align-items: start; }

/* Servidor */
.server-grid { display: flex; align-items: center; gap: var(--sp-6); }
.server-gauge { flex-shrink: 0; }
.server-info { flex: 1; display: flex; flex-direction: column; gap: var(--sp-2); }
.info-row { display: flex; justify-content: space-between; gap: var(--sp-3); padding: 6px 0; border-bottom: 1px solid var(--border); }
.info-row:last-child { border-bottom: none; }
.info-row__k { color: var(--text-muted); font-size: var(--fs-sm); }
.info-row__v { color: var(--text); font-weight: var(--fw-medium); font-size: var(--fs-sm); text-align: right; }
.mono { font-family: var(--font-mono); }

/* Servicios */
.svc-list { display: flex; flex-direction: column; }
.svc-item { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-3) var(--sp-5); border-bottom: 1px solid var(--border); }
.svc-item:last-child { border-bottom: none; }
.svc-name { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-sm); color: var(--text); }
.svc-state { font-size: var(--fs-sm); color: var(--text-muted); text-transform: capitalize; }

/* Acciones rápidas */
.quick-actions { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--sp-2); }
.quick-action {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-3); border-radius: var(--r-md);
  border: 1px solid var(--border);
  color: var(--text-secondary); text-decoration: none;
  font-size: var(--fs-sm); font-weight: var(--fw-medium);
  transition: all var(--t-fast) var(--ease);
}
.quick-action .bi { font-size: 16px; color: var(--color-primary); }
.quick-action:hover { background: var(--surface-inset); color: var(--text); border-color: var(--border-strong); transform: translateY(-1px); }

/* Dominios */
.link-more { font-size: var(--fs-sm); color: var(--color-primary); text-decoration: none; font-weight: var(--fw-medium); display: inline-flex; align-items: center; gap: 4px; }
.link-more:hover { text-decoration: underline; }
.dom-list { display: flex; flex-direction: column; }
.dom-item { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-3) var(--sp-5); border-bottom: 1px solid var(--border); text-decoration: none; transition: background var(--t-fast); }
.dom-item:last-child { border-bottom: none; }
.dom-item:hover { background: var(--surface-inset); }
.dom-name { display: flex; align-items: center; gap: var(--sp-2); color: var(--text); font-weight: var(--fw-medium); }
.dom-name .bi { color: var(--color-primary); }
.dom-meta { display: flex; align-items: center; gap: var(--sp-3); }
.dom-php { font-size: var(--fs-sm); color: var(--text-muted); font-family: var(--font-mono); }

/* Responsive */
@media (max-width: 1100px) {
  .dash-row { grid-template-columns: 1fr 1fr; }
  .dash-server { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  .metrics-grid { grid-template-columns: repeat(2, 1fr); }
  .dash-row { grid-template-columns: 1fr; }
  .quick-actions { grid-template-columns: repeat(2, 1fr); }
}
</style>
