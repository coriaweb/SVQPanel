<template>
  <div>
    <!-- Back + header -->
    <div class="d-flex align-items-center gap-3 mb-4">
      <button class="btn btn-outline-secondary btn-sm" @click="$router.back()">
        <i class="bi bi-arrow-left"></i> Volver
      </button>
      <div v-if="user">
        <h2 class="mb-0">
          <i class="bi bi-person-circle me-2"></i>{{ user.username }}
          <span :class="roleBadgeClass(user.role)" class="badge ms-2 fs-6">{{ roleLabel(user.role) }}</span>
        </h2>
        <small class="text-muted">{{ user.email }}</small>
      </div>
      <div v-else-if="loadingUser" class="spinner-border spinner-border-sm text-secondary"></div>
    </div>

    <div v-if="user" class="row g-4">
      <!-- Info card -->
      <div class="col-md-3">
        <div class="card">
          <div class="card-header"><i class="bi bi-info-circle me-1"></i> Información</div>
          <div class="card-body p-0">
            <ul class="list-group list-group-flush">
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Rol</span>
                <span :class="roleBadgeClass(user.role)" class="badge">{{ roleLabel(user.role) }}</span>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Estado</span>
                <span :class="user.is_active ? 'badge bg-success' : 'badge bg-danger'">
                  {{ user.is_active ? 'Activo' : 'Inactivo' }}
                </span>
              </li>
              <li v-if="user.role === 'reseller'" class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Clientes</span>
                <strong>{{ clients.length }}</strong>
              </li>
              <li v-else class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Dominios</span>
                <strong>{{ domains.length }} / {{ user.domains_limit === 0 ? '∞' : user.domains_limit }}</strong>
              </li>
              <li class="list-group-item d-flex justify-content-between">
                <span class="text-muted">Creado</span>
                <small>{{ formatDate(user.created_at) }}</small>
              </li>
            </ul>
          </div>
          <div class="card-footer">
            <button class="btn btn-sm btn-outline-warning w-100" @click="showEditUser = true">
              <i class="bi bi-pencil me-1"></i> Editar usuario
            </button>
          </div>
        </div>
      </div>

      <!-- Panel principal -->
      <div class="col-md-9">

        <!-- ═══ RESELLER: lista de clientes ═══ -->
        <template v-if="user.role === 'reseller'">
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span><i class="bi bi-people me-1"></i> Clientes de {{ user.username }}</span>
              <button class="btn btn-sm btn-primary" @click="showAddClient = true">
                <i class="bi bi-person-plus"></i> Añadir cliente
              </button>
            </div>
            <div class="card-body">
              <div v-if="loadingClients" class="text-center py-3">
                <div class="spinner-border spinner-border-sm"></div>
              </div>
              <div v-else-if="clients.length === 0" class="alert alert-info mb-0">
                <i class="bi bi-info-circle me-1"></i> Este reseller no tiene clientes aún
              </div>
              <div v-else class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Usuario</th>
                      <th>Email</th>
                      <th>Dominios</th>
                      <th>Estado</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="client in clients" :key="client.id">
                      <td><i class="bi bi-person-circle text-secondary me-1"></i><strong>{{ client.username }}</strong></td>
                      <td>{{ client.email }}</td>
                      <td><i class="bi bi-globe2 me-1 text-muted"></i>{{ client.domains_limit === 0 ? '∞' : client.domains_limit }}</td>
                      <td>
                        <span :class="client.is_active ? 'badge bg-success' : 'badge bg-danger'">
                          {{ client.is_active ? 'Activo' : 'Inactivo' }}
                        </span>
                      </td>
                      <td>
                        <div class="btn-group btn-group-sm">
                          <button class="btn btn-outline-primary" @click="$router.push(`/users/${client.id}/account`)">
                            <i class="bi bi-box-arrow-in-right me-1"></i> Gestionar
                          </button>
                          <button class="btn btn-outline-danger" @click="deleteClientConfirm(client)">
                            <i class="bi bi-trash"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </template>

        <!-- ═══ USER: lista de dominios ═══ -->
        <template v-else>
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span><i class="bi bi-globe2 me-1"></i> Dominios de {{ user.username }}</span>
              <button class="btn btn-sm btn-primary" @click="showAddDomain = true">
                <i class="bi bi-plus-lg"></i> Añadir dominio
              </button>
            </div>
            <div class="card-body">
              <div v-if="loadingDomains" class="text-center py-3">
                <div class="spinner-border spinner-border-sm"></div>
              </div>
              <div v-else-if="domains.length === 0" class="alert alert-info mb-0">
                <i class="bi bi-info-circle me-1"></i> Este usuario no tiene dominios
              </div>
              <div v-else class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Dominio</th>
                      <th>PHP</th>
                      <th>SSL</th>
                      <th>IPv6</th>
                      <th>Estado</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="domain in domains" :key="domain.id">
                      <td>
                        <i class="bi bi-globe text-primary me-1"></i>
                        <a :href="'http://' + domain.domain_name" target="_blank" class="text-decoration-none fw-semibold">
                          {{ domain.domain_name }}
                        </a>
                      </td>
                      <td><span class="badge bg-info text-dark">PHP {{ domain.php_version || '8.2' }}</span></td>
                      <td>
                        <span v-if="domain.ssl_enabled" class="badge bg-success">
                          <i class="bi bi-lock-fill me-1"></i>SSL
                        </span>
                        <span v-else class="badge bg-light text-secondary border">
                          <i class="bi bi-unlock me-1"></i>No
                        </span>
                      </td>
                      <td>
                        <span v-if="domain.ipv6" class="badge bg-primary font-monospace" style="font-size:.7rem" :title="domain.ipv6">
                          <i class="bi bi-diagram-3 me-1"></i>IPv6
                        </span>
                        <span v-else class="badge bg-light text-secondary border">—</span>
                      </td>
                      <td>
                        <span :class="domain.is_active ? 'badge bg-success' : 'badge bg-danger'">
                          {{ domain.is_active ? 'Activo' : 'Inactivo' }}
                        </span>
                      </td>
                      <td class="text-end">
                        <button
                          class="btn btn-sm btn-outline-primary"
                          @click="openDomainManager(domain)"
                        >
                          <i class="bi bi-sliders me-1"></i> Gestionar
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════
         MODAL: Gestionar Dominio (PHP + SSL + IPv6 + Danger Zone)
         ═══════════════════════════════════════════════════════════ -->
    <div v-if="showDomainManager && selectedDomain"
         class="modal d-block" tabindex="-1"
         style="background:rgba(0,0,0,.55); overflow-y:auto;">
      <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">

          <!-- Header -->
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="bi bi-globe text-primary me-2"></i>
              {{ selectedDomain.domain_name }}
            </h5>
            <button type="button" class="btn-close" @click="closeDomainManager"></button>
          </div>

          <!-- Body con secciones -->
          <div class="modal-body p-0">

            <!-- ── Información ── -->
            <div class="px-4 pt-4 pb-3 border-bottom">
              <h6 class="text-muted text-uppercase small mb-3"><i class="bi bi-info-circle me-1"></i> Información</h6>
              <div class="row g-2 small">
                <div class="col-sm-4 text-muted">Ruta web</div>
                <div class="col-sm-8 font-monospace">/home/{{ user.username }}/web/{{ selectedDomain.domain_name }}/public_html</div>
                <div class="col-sm-4 text-muted">Creado</div>
                <div class="col-sm-8">{{ formatDate(selectedDomain.created_at) }}</div>
                <div v-if="selectedDomain.ipv6" class="col-sm-4 text-muted">IPv6</div>
                <div v-if="selectedDomain.ipv6" class="col-sm-8 font-monospace text-primary">{{ selectedDomain.ipv6 }}</div>
              </div>
            </div>

            <!-- ── PHP ── -->
            <div class="px-4 py-3 border-bottom">
              <h6 class="text-muted text-uppercase small mb-3"><i class="bi bi-filetype-php me-1"></i> Versión PHP</h6>
              <form @submit.prevent="handleChangePHP" class="row g-2 align-items-end">
                <div class="col">
                  <select v-model="phpVersion" class="form-select form-select-sm">
                    <option v-for="v in phpAvailableVersions" :key="v" :value="v">PHP {{ v }}</option>
                  </select>
                </div>
                <div class="col-auto">
                  <button type="submit" class="btn btn-sm btn-primary" :disabled="changingPHP">
                    <span v-if="changingPHP" class="spinner-border spinner-border-sm me-1"></span>
                    <i v-else class="bi bi-check-lg me-1"></i>
                    Aplicar
                  </button>
                </div>
              </form>
              <div class="form-text mt-1">Versión actual: <strong>PHP {{ selectedDomain.php_version || '8.2' }}</strong></div>
            </div>

            <!-- ── SSL ── -->
            <div class="px-4 py-3 border-bottom">
              <h6 class="text-muted text-uppercase small mb-3"><i class="bi bi-lock me-1"></i> Certificado SSL</h6>

              <div v-if="selectedDomain.ssl_enabled" class="d-flex align-items-center gap-3">
                <span class="badge bg-success fs-6"><i class="bi bi-lock-fill me-1"></i> SSL activo</span>
                <div class="text-muted small" v-if="selectedDomain.ssl_expires">
                  Expira: {{ formatDate(selectedDomain.ssl_expires) }}
                </div>
                <button class="btn btn-sm btn-outline-danger ms-auto" @click="handleDeleteSSL" :disabled="sslLoading">
                  <span v-if="sslLoading" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-x-circle me-1"></i>
                  Revocar SSL
                </button>
              </div>

              <div v-else>
                <div class="d-flex align-items-center gap-3 mb-2">
                  <span class="badge bg-secondary"><i class="bi bi-unlock me-1"></i> Sin SSL</span>
                </div>
                <button class="btn btn-sm btn-success" @click="handleCreateSSL" :disabled="sslLoading">
                  <span v-if="sslLoading" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-shield-check me-1"></i>
                  Instalar certificado Let's Encrypt
                </button>
                <div class="form-text mt-1">
                  El dominio debe resolver a este servidor para que Let's Encrypt funcione.
                </div>
              </div>
            </div>

            <!-- ── IPv6 ── -->
            <div class="px-4 py-3 border-bottom">
              <h6 class="text-muted text-uppercase small mb-3"><i class="bi bi-diagram-3 me-1"></i> IPv6 dedicada</h6>
              <IPv6Manager :domain="selectedDomain" @reload="onDomainReload" />
            </div>

            <!-- ── Danger Zone ── -->
            <div class="px-4 py-3 bg-light">
              <h6 class="text-danger text-uppercase small mb-3"><i class="bi bi-exclamation-triangle me-1"></i> Zona de peligro</h6>
              <div v-if="!confirmDeleteDomain">
                <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteDomain = true">
                  <i class="bi bi-trash me-1"></i> Eliminar dominio
                </button>
                <div class="form-text mt-1 text-danger">
                  Esto eliminará el dominio, todos sus archivos y la configuración nginx.
                </div>
              </div>
              <div v-else class="alert alert-danger mb-0">
                <p class="mb-2 fw-bold">¿Confirmar eliminación de <em>{{ selectedDomain.domain_name }}</em>?</p>
                <p class="small mb-3">Se eliminarán todos los archivos en <code>/home/{{ user.username }}/web/{{ selectedDomain.domain_name }}/</code></p>
                <div class="d-flex gap-2">
                  <button class="btn btn-danger btn-sm" @click="handleDeleteDomain" :disabled="deletingDomain">
                    <span v-if="deletingDomain" class="spinner-border spinner-border-sm me-1"></span>
                    Sí, eliminar
                  </button>
                  <button class="btn btn-secondary btn-sm" @click="confirmDeleteDomain = false">Cancelar</button>
                </div>
              </div>
            </div>

          </div><!-- /modal-body -->

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeDomainManager">Cerrar</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: editar usuario -->
    <Modal :isOpen="showEditUser" title="Editar Usuario" @close="showEditUser = false">
      <UserForm :user="user" @submit="onUserUpdated" @cancel="showEditUser = false" />
    </Modal>

    <!-- Modal: añadir cliente (reseller) -->
    <Modal :isOpen="showAddClient" title="Añadir Cliente" @close="showAddClient = false">
      <UserForm :parentId="user?.id" @submit="onClientAdded" @cancel="showAddClient = false" />
    </Modal>

    <!-- Modal: añadir dominio -->
    <Modal :isOpen="showAddDomain" title="Añadir Dominio" @close="showAddDomain = false">
      <form @submit.prevent="handleAddDomain">
        <div class="mb-3">
          <label class="form-label">Nombre de dominio</label>
          <input v-model="newDomain.domain_name" type="text" class="form-control" placeholder="ejemplo.com" required />
        </div>
        <div class="mb-3">
          <label class="form-label">Versión PHP</label>
          <select v-model="newDomain.php_version" class="form-select">
            <option v-for="v in phpAvailableVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </div>
        <div class="d-flex gap-2">
          <button type="submit" class="btn btn-primary" :disabled="addingDomain">
            <span v-if="addingDomain" class="spinner-border spinner-border-sm me-1"></span>
            Crear dominio
          </button>
          <button type="button" class="btn btn-secondary" @click="showAddDomain = false">Cancelar</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import UserForm from '../components/UserForm.vue'
import IPv6Manager from '../components/IPv6Manager.vue'

export default {
  name: 'UserAccount',
  components: { Modal, UserForm, IPv6Manager },
  setup() {
    const route = useRoute()
    const store = useMainStore()
    const userId = parseInt(route.params.id)

    const user           = ref(null)
    const clients        = ref([])
    const domains        = ref([])
    const loadingUser    = ref(true)
    const loadingClients = ref(false)
    const loadingDomains = ref(false)

    const showEditUser       = ref(false)
    const showAddClient      = ref(false)
    const showAddDomain      = ref(false)
    const addingDomain       = ref(false)
    const newDomain          = ref({ domain_name: '', php_version: '8.2' })

    // Domain manager modal
    const showDomainManager  = ref(false)
    const selectedDomain     = ref(null)

    // PHP
    const phpVersion           = ref('8.2')
    const changingPHP          = ref(false)
    const phpAvailableVersions = ref(['7.4', '8.0', '8.1', '8.2', '8.3', '8.4', '8.5'])

    // SSL
    const sslLoading = ref(false)

    // Delete domain
    const confirmDeleteDomain = ref(false)
    const deletingDomain      = ref(false)

    // ─── Helpers ────────────────────────────────────────────────────────────
    const roleLabel     = (role) => ({ admin: '🔑 Admin', reseller: '🏪 Reseller', user: '👤 Usuario' }[role] ?? role)
    const roleBadgeClass= (role) => ({ admin: 'bg-danger', reseller: 'bg-warning text-dark', user: 'bg-secondary' }[role] ?? 'bg-secondary')
    const formatDate    = (d) => d ? new Date(d).toLocaleDateString('es-ES', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

    // ─── Load data ──────────────────────────────────────────────────────────
    const loadUser = async () => {
      loadingUser.value = true
      try { user.value = await api.getUser(userId) }
      catch (e) { store.showNotification('Error al cargar usuario', 'danger') }
      finally { loadingUser.value = false }
    }

    const loadClients = async () => {
      loadingClients.value = true
      try {
        const data = await api.getUsers(0, 100, null, userId)
        clients.value = Array.isArray(data) ? data : []
      } catch (e) { store.showNotification('Error al cargar clientes', 'danger') }
      finally { loadingClients.value = false }
    }

    const loadDomains = async () => {
      loadingDomains.value = true
      try {
        const data = await api.getDomains(userId, 0, 100)
        domains.value = Array.isArray(data) ? data : []
      } catch (e) { store.showNotification('Error al cargar dominios', 'danger') }
      finally { loadingDomains.value = false }
    }

    const loadPHPVersions = async () => {
      try {
        const data = await api.getPHPVersions()
        if (data?.versions?.length) phpAvailableVersions.value = data.versions
      } catch { /* usa la lista por defecto */ }
    }

    // ─── Domain manager ─────────────────────────────────────────────────────
    const openDomainManager = (domain) => {
      selectedDomain.value = { ...domain }
      phpVersion.value = domain.php_version || '8.2'
      confirmDeleteDomain.value = false
      showDomainManager.value = true
    }

    const closeDomainManager = () => {
      showDomainManager.value = false
      selectedDomain.value = null
    }

    // Cuando IPv6Manager emite reload, refrescamos dominio y lista
    const onDomainReload = async () => {
      await loadDomains()
      // Actualizar selectedDomain con los datos frescos
      if (selectedDomain.value) {
        const fresh = domains.value.find(d => d.id === selectedDomain.value.id)
        if (fresh) selectedDomain.value = { ...fresh }
      }
    }

    // ─── PHP ────────────────────────────────────────────────────────────────
    const handleChangePHP = async () => {
      changingPHP.value = true
      try {
        await api.changePHPVersion(selectedDomain.value.id, phpVersion.value)
        selectedDomain.value.php_version = phpVersion.value
        store.showNotification(`PHP cambiado a ${phpVersion.value}`, 'success')
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al cambiar PHP: ' + e.message, 'danger')
      } finally {
        changingPHP.value = false
      }
    }

    // ─── SSL ────────────────────────────────────────────────────────────────
    const handleCreateSSL = async () => {
      sslLoading.value = true
      try {
        await api.createSSL(selectedDomain.value.id, {})
        store.showNotification('SSL instalado correctamente', 'success')
        await onDomainReload()
      } catch (e) {
        store.showNotification('Error al instalar SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    const handleDeleteSSL = async () => {
      sslLoading.value = true
      try {
        await api.deleteSSL(selectedDomain.value.id)
        store.showNotification('SSL revocado', 'success')
        await onDomainReload()
      } catch (e) {
        store.showNotification('Error al revocar SSL: ' + e.message, 'danger')
      } finally {
        sslLoading.value = false
      }
    }

    // ─── Delete domain ───────────────────────────────────────────────────────
    const handleDeleteDomain = async () => {
      deletingDomain.value = true
      try {
        await api.deleteDomain(selectedDomain.value.id)
        store.showNotification('Dominio eliminado', 'success')
        closeDomainManager()
        await loadDomains()
      } catch (e) {
        store.showNotification('Error al eliminar: ' + e.message, 'danger')
      } finally {
        deletingDomain.value = false
      }
    }

    // ─── Add domain ──────────────────────────────────────────────────────────
    const handleAddDomain = async () => {
      addingDomain.value = true
      try {
        await api.createDomain({
          user_id: userId,
          domain_name: newDomain.value.domain_name,
          php_version: newDomain.value.php_version
        })
        store.showNotification('Dominio creado', 'success')
        showAddDomain.value = false
        newDomain.value = { domain_name: '', php_version: '8.2' }
        await loadDomains()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        addingDomain.value = false
      }
    }

    // ─── User actions ────────────────────────────────────────────────────────
    const onUserUpdated = async () => { showEditUser.value = false; await loadUser() }
    const onClientAdded = async () => { showAddClient.value = false; await loadClients() }

    const deleteClientConfirm = (client) => {
      if (confirm(`¿Eliminar cliente "${client.username}"?\nEsto eliminará también sus dominios y archivos.`)) {
        api.deleteUser(client.id)
          .then(() => { store.showNotification('Cliente eliminado', 'success'); loadClients() })
          .catch(e => store.showNotification('Error: ' + e.message, 'danger'))
      }
    }

    // ─── Init ────────────────────────────────────────────────────────────────
    onMounted(async () => {
      await loadUser()
      await loadPHPVersions()
      if (user.value?.role === 'reseller') {
        await loadClients()
      } else {
        await loadDomains()
      }
    })

    return {
      user, clients, domains,
      loadingUser, loadingClients, loadingDomains,
      showEditUser, showAddClient, showAddDomain, addingDomain, newDomain,
      showDomainManager, selectedDomain,
      phpVersion, changingPHP, phpAvailableVersions,
      sslLoading,
      confirmDeleteDomain, deletingDomain,
      roleLabel, roleBadgeClass, formatDate,
      openDomainManager, closeDomainManager, onDomainReload,
      handleChangePHP, handleCreateSSL, handleDeleteSSL,
      handleDeleteDomain, handleAddDomain,
      onUserUpdated, onClientAdded, deleteClientConfirm,
    }
  }
}
</script>
