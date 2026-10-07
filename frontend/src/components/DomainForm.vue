<template>
  <form @submit.prevent="handleSubmit">

    <!-- Tipo: dominio o subdominio (solo en creación) -->
    <div v-if="!isEditing" class="mb-3">
      <label class="form-label">Tipo</label>
      <div class="d-flex gap-3">
        <div class="form-check">
          <input id="type_domain" class="form-check-input" type="radio" :value="false" v-model="form.is_subdomain" />
          <label for="type_domain" class="form-check-label"><i class="bi bi-globe2 me-1"></i>Dominio</label>
        </div>
        <div class="form-check">
          <input id="type_sub" class="form-check-input" type="radio" :value="true" v-model="form.is_subdomain"
                 :disabled="parentCandidates.length === 0" />
          <label for="type_sub" class="form-check-label"><i class="bi bi-diagram-3 me-1"></i>Subdominio</label>
        </div>
      </div>
      <small v-if="parentCandidates.length === 0" class="text-muted">
        No hay dominios a los que colgar un subdominio (crea primero el dominio padre).
      </small>
    </div>

    <!-- Subdominio: nombre + dominio padre -->
    <div v-if="!isEditing && form.is_subdomain" class="mb-3">
      <label class="form-label">Subdominio</label>
      <div class="input-group">
        <input v-model="form.sub_label" type="text" class="form-control" placeholder="gestion" />
        <span class="input-group-text">.</span>
        <select v-model="form.parent_name" class="form-select">
          <option v-for="p in parentCandidates" :key="p" :value="p">{{ p }}</option>
        </select>
      </div>
      <small class="text-muted">Se creará <code>{{ form.sub_label || 'nombre' }}.{{ form.parent_name }}</code> con su propia web; en DNS se añade dentro de la zona padre.</small>
    </div>

    <!-- Dominio normal: nombre completo -->
    <div v-else-if="!isEditing" class="mb-3">
      <label class="form-label">Nombre de Dominio</label>
      <input
        v-model="form.domain_name"
        type="text"
        class="form-control"
        placeholder="ejemplo.com"
        required
      />
      <small class="text-muted">Ej: ejemplo.com</small>
    </div>

    <!-- Edición: nombre fijo -->
    <div v-else class="mb-3">
      <label class="form-label">Nombre de Dominio</label>
      <input v-model="form.domain_name" type="text" class="form-control" disabled />
    </div>

    <!-- Aviso: dominio solo correo/DNS (al editar) -->
    <div v-if="isEditing && isMailDnsOnly" class="alert alert-info py-2 px-3 mb-3 small">
      <i class="bi bi-envelope me-1"></i>
      <strong>Solo correo / DNS.</strong> Este dominio no aloja la web aquí (su registro A
      apunta a otro servidor), así que no hay opciones de PHP, SSL, caché ni plantilla.
      El correo y la zona DNS se gestionan en sus propias secciones.
    </div>

    <!-- Selector de usuario: solo para admin/reseller -->
    <div v-if="isAdminOrReseller && !isEditing" class="mb-3">
      <label class="form-label">Usuario (cliente propietario)</label>
      <select v-model="form.user_id" class="form-select" required>
        <option value="">Selecciona un cliente</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.username }} ({{ user.email }})
        </option>
      </select>
      <div v-if="users.length === 0" class="form-text text-warning">
        No hay cuentas de cliente. Los administradores no pueden alojar dominios;
        crea primero un cliente en la sección Usuarios.
      </div>
    </div>

    <!-- Solo correo/DNS: el dominio no se aloja aquí (su web/registro A apunta a
         otro servidor); aquí solo se gestiona correo y/o DNS. -->
    <div v-if="!isEditing && !form.is_subdomain" class="mb-3 form-check">
      <input id="mail_dns_only" v-model="form.mail_dns_only" type="checkbox" class="form-check-input" />
      <label for="mail_dns_only" class="form-check-label">
        Solo correo / DNS (sin alojar la web aquí)
      </label>
      <div class="form-text">
        Marca esto si la web del dominio está en otro servidor (su registro A apunta fuera)
        y aquí solo quieres gestionar el <strong>correo</strong> y/o la <strong>zona DNS</strong>.
        No se creará vhost ni PHP.
      </div>
    </div>

    <div class="mb-3" v-if="isWebDomain && !isEditing">
      <label class="form-label">Versión PHP</label>
      <select v-model="form.php_version" class="form-select" :required="isWebDomain">
        <option value="">Selecciona versión</option>
        <option v-for="version in availablePhpVersions" :key="version" :value="version">
          PHP {{ version }}{{ deprecatedPhp.includes(version) ? ' ⚠ sin soporte (EOL)' : '' }}
        </option>
      </select>
      <div class="form-text">Solo se muestran versiones instaladas y activas en el servidor.</div>
      <div v-if="deprecatedPhp.includes(form.php_version)" class="alert alert-warning py-2 px-3 mb-0 mt-2 small">
        <i class="bi bi-exclamation-triangle me-1"></i>
        PHP {{ form.php_version }} está <strong>sin soporte de seguridad oficial</strong> (EOL).
        Úsala solo si el sitio lo requiere; considera actualizarlo a una versión con soporte.
      </div>
    </div>

    <div class="mb-3 form-check">
      <input id="is_active" v-model="form.is_active" type="checkbox" class="form-check-input" />
      <label for="is_active" class="form-check-label">Dominio activo</label>
    </div>

    <!-- IPs del servidor (creación y edición). No aplica a solo correo/DNS: la
         IPv4/IPv6 de aquí son para que NGINX escuche en ellas (el vhost), y un
         dominio sin web no tiene vhost. Para publicar un AAAA en la zona se hace
         desde la vista DNS; el correo usa la IPv6 global del servidor.
         Solo al CREAR: en un dominio existente se cambian en su ficha (pestaña Red). -->
    <template v-if="isWebDomain && !isEditing">
    <hr class="my-3" />
    <p class="fw-semibold mb-2 text-muted small text-uppercase">
      <i class="bi bi-hdd-network me-1"></i> Direcciones IP
    </p>
    <div class="mb-3">
      <label class="form-label small mb-1">IPv4</label>
      <select v-model="form.ipv4" class="form-select">
        <option :value="null">— IP principal del servidor (por defecto) —</option>
        <option
          v-for="ip in serverIps"
          :key="ip.address"
          :value="ip.address"
        >{{ ip.address }}{{ ip.note ? ' — ' + ip.note : '' }}</option>
      </select>
      <div class="form-text">
        Al cambiarla se regenera el vhost, se actualiza la IP de salida del correo
        y los registros A de su zona DNS que apuntaban a la IP anterior pasan a la
        nueva (los que apuntan a otras IPs no se tocan). Dejar en blanco = IP
        principal del servidor.
      </div>
    </div>
    <div v-if="ipv6Enabled" class="mb-3">
      <label class="form-label small mb-1">
        IPv6 <span class="text-muted fw-normal">(opcional)</span>
      </label>
      <div v-if="ipv6Loading" class="text-muted small py-1">
        <span class="spinner-border spinner-border-sm me-1"></span> Generando sugerencias…
      </div>
      <div v-else class="d-flex flex-column gap-1">
        <div class="form-check">
          <input class="form-check-input" type="radio" :name="'ipv6_'+_uid" :id="'ipv6_none_'+_uid"
            :value="null" v-model="form.ipv6" />
          <label class="form-check-label text-muted" :for="'ipv6_none_'+_uid">
            Ninguna (asignar después)
          </label>
        </div>
        <div v-for="(ip, i) in ipv6Suggestions" :key="ip" class="form-check">
          <input class="form-check-input" type="radio" :name="'ipv6_'+_uid" :id="'ipv6_'+i+'_'+_uid"
            :value="ip" v-model="form.ipv6" />
          <label class="form-check-label font-monospace small" :for="'ipv6_'+i+'_'+_uid">
            {{ ip }}
          </label>
        </div>
        <div v-if="isEditing && form.ipv6 && !ipv6Suggestions.includes(form.ipv6)" class="form-check">
          <input class="form-check-input" type="radio" :name="'ipv6_'+_uid" :id="'ipv6_current_'+_uid"
            :value="form.ipv6" v-model="form.ipv6" checked />
          <label class="form-check-label font-monospace small text-success" :for="'ipv6_current_'+_uid">
            {{ form.ipv6 }} <span class="badge bg-success ms-1">actual</span>
          </label>
        </div>
      </div>
      <div class="form-text mt-1">
        Selecciona una IP dedicada del rango del servidor para este dominio.
      </div>
    </div>
    </template>

    <!-- Plantilla web: solo al CREAR. Para un dominio existente se aplica desde
         su ficha (pestaña Avanzado), que valida y revierte si algo falla. -->
    <template v-if="isWebDomain && isEditing">
    <hr class="my-3" />
    <div class="small text-muted mb-3">
      <i class="bi bi-info-circle me-1"></i>
      El resto de ajustes del dominio están en su <strong>ficha</strong> (pulsa el nombre del dominio):
      <ul class="mb-0 mt-1">
        <li><strong>PHP</strong>: versión, php.ini, recursos y funciones de sistema.</li>
        <li><strong>SSL</strong>: certificado, HTTPS forzado y HSTS.</li>
        <li><strong>Red</strong>: IPv4 dedicada e IPv6.</li>
        <li><strong>Protección</strong>: límite de peticiones por IP y bloqueo de bots.</li>
        <li><strong>Avanzado</strong>: plantilla web, redirección, raíz de documentos y directivas.</li>
        <li><strong>Resumen</strong>: caché de página.</li>
      </ul>
    </div>
    </template>
    <template v-if="isWebDomain && !isEditing">
    <hr class="my-3" />
    <p class="fw-semibold mb-2 text-muted small text-uppercase">
      <i class="bi bi-layout-text-window-reverse me-1"></i> Plantilla web
    </p>

    <div class="mb-3">
      <select v-model="form.selected_template_id" class="form-select">
        <option :value="null">— Sin plantilla (configuración por defecto) —</option>
        <optgroup
          v-for="cat in templateCategories"
          :key="cat.key"
          :label="cat.label"
        >
          <option
            v-for="tpl in templatesByCategory(cat.key)"
            :key="tpl.id"
            :value="tpl.id"
          >{{ tpl.name }}</option>
        </optgroup>
      </select>
    </div>

    <!-- Preview de la plantilla seleccionada -->
    <div v-if="selectedTemplate" class="alert alert-info py-2 px-3 mb-3 small">
      <div class="fw-semibold mb-1">
        <i class="bi bi-info-circle me-1"></i>{{ selectedTemplate.name }}
      </div>
      <div class="text-muted mb-2">{{ selectedTemplate.description }}</div>
      <div class="d-flex flex-wrap gap-2">
        <span v-if="selectedTemplate.fastcgi_cache_default" class="badge bg-warning text-dark">
          <i class="bi bi-lightning-charge me-1"></i>Caché FastCGI activada
        </span>
        <span v-if="selectedTemplate.php_ini_overrides" class="badge bg-secondary">
          <i class="bi bi-cpu me-1"></i>Overrides PHP ini
        </span>
        <span v-if="selectedTemplate.nginx_extra" class="badge bg-secondary">
          <i class="bi bi-code me-1"></i>Config nginx extra
        </span>
        <template v-if="selectedTemplate.php_ini_overrides">
          <span
            v-for="(val, key) in parsedPhpOverrides"
            :key="key"
            class="badge bg-light text-dark border"
          >{{ key }}: {{ val }}</span>
        </template>
      </div>
    </div>
    </template>

    <!-- Opciones extras (solo en creación) -->
    <template v-if="!isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Servicios adicionales</p>

      <div class="mb-2 form-check">
        <input id="dns_enabled" v-model="form.dns_enabled" type="checkbox" class="form-check-input" />
        <label for="dns_enabled" class="form-check-label">
          <i class="bi bi-diagram-3 me-1"></i> Soporte DNS
          <small class="text-muted">(Crear zona en servidor DNS)</small>
        </label>
      </div>

      <div class="mb-3 form-check">
        <input id="mail_enabled" v-model="form.mail_enabled" type="checkbox" class="form-check-input" />
        <label for="mail_enabled" class="form-check-label">
          <i class="bi bi-envelope me-1"></i> Soporte Correo
          <small class="text-muted">(Crear dominio de correo)</small>
        </label>
      </div>
    </template>


    <div class="d-flex gap-2 mt-3">
      <button type="submit" class="btn btn-primary" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        {{ isEditing ? 'Actualizar' : 'Crear' }} Dominio
      </button>
      <button type="button" class="btn btn-secondary" @click="$emit('cancel')" :disabled="loading">
        Cancelar
      </button>
    </div>
  </form>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

import { TEMPLATE_CATEGORIES } from '../utils/templates'

export default {
  name: 'DomainForm',
  props: {
    domain:      { type: Object, default: null },
    // Versiones PHP ya cargadas por el padre (para no hacer doble petición)
    phpVersions: { type: Array, default: () => [] },
  },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading   = ref(false)
    const isEditing = ref(!!props.domain)
    const users     = ref([])
    const localPhpVersions = ref([])
    const deprecatedPhp = ref([])   // versiones PHP EOL (sin soporte oficial)
    const templates  = ref([])
    const serverIps  = ref([])

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    // Dominio solo correo/DNS (no aloja web). En edición se lee del dominio; en
    // creación, del checkbox del formulario. Las secciones web no aplican.
    const isMailDnsOnly = computed(() =>
      isEditing.value ? !!props.domain?.mail_dns_only : !!form.value.mail_dns_only
    )
    const isWebDomain = computed(() => !isMailDnsOnly.value)

    // Versiones disponibles: usa las del padre si las pasa, si no carga propias
    const availablePhpVersions = computed(() =>
      props.phpVersions.length ? props.phpVersions : localPhpVersions.value
    )

    const form = ref({
      domain_name: props.domain?.domain_name || '',
      user_id:     props.domain?.user_id     || (isAdminOrReseller.value ? '' : store.currentUser?.id),
      php_version: props.domain?.php_version || '',
      is_active:   props.domain?.is_active   ?? true,
      dns_enabled:  false,
      mail_enabled: false,
      // Solo correo/DNS: el dominio no se aloja aquí (web en otro servidor).
      mail_dns_only: false,
      // Subdominio (solo creación)
      is_subdomain: false,
      sub_label:    '',
      parent_name:  '',
      selected_template_id: null,
      // IPs (solo en creación; en un dominio existente, ficha → Red)
      ipv4: null,
      ipv6: null,
    })

    // ── Subdominios: dominios padre candidatos (los que NO son subdominios) ──
    const parentCandidates = ref([])
    const loadParentCandidates = async () => {
      try {
        // Para admin/reseller, los candidatos del cliente elegido; si no, los propios.
        const uid = isAdminOrReseller.value ? (form.value.user_id || null) : null
        const data = await api.getDomains(uid, 0, 1000)
        const list = Array.isArray(data) ? data : (data?.domains || [])
        parentCandidates.value = list
          .filter(d => !d.is_subdomain)
          .map(d => d.domain_name)
          .sort()
        if (parentCandidates.value.length && !form.value.parent_name) {
          form.value.parent_name = parentCandidates.value[0]
        }
      } catch { parentCandidates.value = [] }
    }

    // ── Plantillas ─────────────────────────────────────────────────────────

    const templateCategories = TEMPLATE_CATEGORIES

    const templatesByCategory = (cat) =>
      templates.value.filter(t => t.category === cat)

    const selectedTemplate = computed(() =>
      form.value.selected_template_id
        ? templates.value.find(t => t.id === form.value.selected_template_id) || null
        : null
    )

    const parsedPhpOverrides = computed(() => {
      if (!selectedTemplate.value?.php_ini_overrides) return {}
      try { return JSON.parse(selectedTemplate.value.php_ini_overrides) }
      catch { return {} }
    })

    const loadTemplates = async () => {
      try {
        templates.value = await api.getTemplates() || []
      } catch { templates.value = [] }
    }

    const ipv6Enabled = ref(false)
    const ipv6Suggestions = ref([])
    const ipv6Loading = ref(false)
    const _uid = Math.random().toString(36).slice(2)

    const loadServerIps = async () => {
      try {
        const data = await api.getServerIps() || []
        serverIps.value = data.filter(ip => !ip.is_ipv6 && ip.is_active)
      } catch { serverIps.value = [] }
      // Comprobar si IPv6 está habilitado en settings y cargar sugerencias
      try {
        const s = await api.getSettings()
        ipv6Enabled.value = !!(s.ipv6_enabled && s.ipv6_range)
      } catch { ipv6Enabled.value = false }
      if (ipv6Enabled.value) {
        ipv6Loading.value = true
        try {
          // Excluir la IP actual si ya tiene una asignada
          const exclude = form.value.ipv6 || null
          const data = await api.getNextIPv6(exclude, 3)
          ipv6Suggestions.value = data.suggestions || (data.next_ipv6 ? [data.next_ipv6] : [])
        } catch { ipv6Suggestions.value = [] }
        finally { ipv6Loading.value = false }
      }
    }

    // ── Usuarios / PHP ─────────────────────────────────────────────────────

    const loadUsers = async () => {
      if (!isAdminOrReseller.value) return
      try {
        const data = await api.getUsers()
        // Separación administración/hosting: los admins no pueden ser dueños de
        // dominios (el backend lo rechaza). No los mostramos como opción.
        users.value = (Array.isArray(data) ? data : [])
          .filter(u => u.role !== 'admin' && !u.is_admin)
      } catch { /* silencioso */ }
    }

    const loadPHPVersions = async () => {
      if (props.phpVersions.length) return   // el padre ya las pasó
      try {
        const data = await api.getPHPVersions()
        localPhpVersions.value = data?.versions?.length ? data.versions : ['8.2']
        deprecatedPhp.value = data?.deprecated || []
      } catch {
        localPhpVersions.value = ['8.2']
      }
      // Ajustar versión seleccionada si la actual no está en la lista
      if (!form.value.php_version || !availablePhpVersions.value.includes(form.value.php_version)) {
        form.value.php_version = availablePhpVersions.value[0] || '8.2'
      }
    }

    // ── Submit ─────────────────────────────────────────────────────────────

    const handleSubmit = async () => {
      loading.value = true
      try {
        if (isEditing.value) {
          // El resto de ajustes (PHP, IPs, SSL, caché, redirección, límite de
          // peticiones, funciones de sistema) se cambian en la ficha del dominio.
          await api.updateDomain(props.domain.id, { is_active: form.value.is_active })
          store.showNotification('Dominio actualizado correctamente', 'success')
        } else {
          const userId = isAdminOrReseller.value
            ? form.value.user_id
            : store.currentUser?.id
          // Subdominio: componer el FQDN y forzar el tipo + DNS (el registro va a
          // la zona padre). Validar el nombre del subdominio.
          let domainName = form.value.domain_name
          let dnsEnabled = form.value.dns_enabled
          if (form.value.is_subdomain) {
            const label = (form.value.sub_label || '').trim().toLowerCase()
            if (!label || !/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(label)) {
              store.showNotification('Nombre de subdominio no válido (a-z, 0-9, guiones).', 'danger')
              loading.value = false
              return
            }
            domainName = `${label}.${form.value.parent_name}`
            dnsEnabled = true   // el subdominio necesita su A en la zona padre
          }
          const mailDnsOnly = form.value.mail_dns_only && !form.value.is_subdomain
          const created = await api.createDomain({
            domain_name:  domainName,
            user_id:      userId,
            // Sin web → PHP irrelevante; el backend ignora el valor.
            php_version:  mailDnsOnly ? '8.2' : form.value.php_version,
            is_active:    form.value.is_active,
            dns_enabled:  dnsEnabled,
            mail_enabled: form.value.mail_enabled,
            mail_dns_only: mailDnsOnly,
            is_subdomain: form.value.is_subdomain || null,
            ipv4:         form.value.ipv4 || null,
            ipv6:         form.value.ipv6 || null,
          })
          // Aplicar plantilla tras crear el dominio (no aplica a solo-correo/DNS)
          if (!mailDnsOnly && form.value.selected_template_id && created?.id) {
            try {
              await api.applyTemplate(created.id, form.value.selected_template_id, {
                ttl_minutes: 60,
              })
              store.showNotification(
                `Dominio creado y plantilla "${selectedTemplate.value?.name}" aplicada`,
                'success'
              )
            } catch {
              store.showNotification('Dominio creado (la plantilla no se pudo aplicar)', 'warning')
            }
          } else {
            store.showNotification('Dominio creado correctamente', 'success')
          }
        }
        emit('submit')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    onMounted(async () => {
      await Promise.all([loadUsers(), loadPHPVersions(), loadTemplates(), loadServerIps(),
                         isEditing.value ? Promise.resolve() : loadParentCandidates()])
      // Si la versión guardada no está en la lista, seleccionar la primera disponible
      if (form.value.php_version && !availablePhpVersions.value.includes(form.value.php_version)) {
        form.value.php_version = availablePhpVersions.value[0] || '8.2'
      } else if (!form.value.php_version && availablePhpVersions.value.length) {
        form.value.php_version = availablePhpVersions.value[0]
      }
    })

    return {
      form, loading, isEditing, users,
      isAdminOrReseller, isWebDomain, isMailDnsOnly, availablePhpVersions, deprecatedPhp,
      templates, templateCategories, templatesByCategory,
      selectedTemplate, parsedPhpOverrides,
      serverIps, ipv6Enabled, ipv6Suggestions, ipv6Loading, _uid,
      parentCandidates,
      handleSubmit,
    }
  }
}
</script>
