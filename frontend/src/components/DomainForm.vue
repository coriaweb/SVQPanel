<template>
  <form @submit.prevent="handleSubmit">

    <div class="mb-3">
      <label class="form-label">Nombre de Dominio</label>
      <input
        v-model="form.domain_name"
        type="text"
        class="form-control"
        placeholder="ejemplo.com"
        required
        :disabled="isEditing"
      />
      <small class="text-muted">Ej: ejemplo.com o sub.ejemplo.com</small>
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

    <div class="mb-3">
      <label class="form-label">Versión PHP</label>
      <select v-model="form.php_version" class="form-select" required>
        <option value="">Selecciona versión</option>
        <option v-for="version in availablePhpVersions" :key="version" :value="version">
          PHP {{ version }}
        </option>
      </select>
      <div class="form-text">Solo se muestran versiones instaladas y activas en el servidor.</div>
    </div>

    <div class="mb-3 form-check">
      <input id="is_active" v-model="form.is_active" type="checkbox" class="form-check-input" />
      <label for="is_active" class="form-check-label">Dominio activo</label>
    </div>

    <!-- IPs del servidor (creación y edición) -->
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
        Nginx escuchará en esta IP. Dejar en blanco para usar la IP principal del servidor.
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

    <!-- Redirección y docroot (solo al editar) -->
    <template v-if="isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">
        <i class="bi bi-arrow-right-circle me-1"></i> Redirección y raíz de documentos
      </p>

      <div class="mb-2 form-check">
        <input id="redirect_enabled" v-model="form.redirect_enabled" type="checkbox" class="form-check-input" />
        <label for="redirect_enabled" class="form-check-label">
          Redirigir este dominio a otra URL (301 permanente)
        </label>
      </div>
      <div v-if="form.redirect_enabled" class="mb-3 ps-4">
        <label class="form-label small mb-1">URL de destino</label>
        <input
          v-model="form.redirect_to"
          type="url"
          class="form-control"
          :class="{ 'is-invalid': redirectError }"
          placeholder="https://otro-dominio.com"
        />
        <div v-if="redirectError" class="invalid-feedback">{{ redirectError }}</div>
        <div class="form-text">El dominio responderá con HTTP 301 a esta URL en todas las rutas.</div>
      </div>

      <div class="mb-3" v-if="!form.redirect_enabled">
        <label class="form-label small mb-1">
          Raíz de documentos personalizada
          <span class="text-muted fw-normal">(opcional)</span>
        </label>
        <input
          v-model="form.custom_docroot"
          type="text"
          class="form-control"
          :class="{ 'is-invalid': docrootError }"
          placeholder="/home/usuario/web/dominio/app/public"
        />
        <div v-if="docrootError" class="invalid-feedback">{{ docrootError }}</div>
        <div class="form-text">
          Ruta absoluta en el servidor. Dejar vacío para usar
          <code>/home/usuario/web/dominio/public_html</code> (por defecto).
        </div>
      </div>
    </template>

    <!-- Plantilla web (creación Y edición) -->
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
      <!-- Al editar: aviso de que se aplicará al guardar -->
      <div v-if="isEditing" class="mt-2 text-warning fw-semibold small">
        <i class="bi bi-exclamation-triangle me-1"></i>
        La plantilla se aplicará al hacer clic en "Actualizar Dominio"
      </div>
    </div>

    <!-- Rendimiento (solo al editar: requiere un dominio ya existente) -->
    <template v-if="isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Rendimiento</p>

      <div class="mb-2 form-check">
        <input id="fcgi_cache" v-model="form.fastcgi_cache_enabled" type="checkbox" class="form-check-input" />
        <label for="fcgi_cache" class="form-check-label">
          <i class="bi bi-lightning-charge me-1"></i> Habilitar caché FastCGI (NGINX)
        </label>
      </div>
      <div v-if="form.fastcgi_cache_enabled" class="mb-3 ps-4">
        <label class="form-label small mb-1">Duración de la caché (minutos)</label>
        <input
          v-model.number="form.fastcgi_cache_ttl_minutes"
          type="number" min="1" max="1440"
          class="form-control form-control-sm"
          style="max-width:160px"
        />
        <div class="form-text">Tiempo que NGINX cachea las respuestas PHP. Ej: 2, 30, 60.</div>
      </div>

      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Protección anti-abuso</p>

      <div class="mb-2 form-check">
        <input id="rate_limit" v-model="form.rate_limit_enabled" type="checkbox" class="form-check-input" />
        <label for="rate_limit" class="form-check-label">
          <i class="bi bi-shield-exclamation me-1"></i> Limitar peticiones por IP (NGINX)
        </label>
      </div>
      <div v-if="form.rate_limit_enabled" class="mb-3 ps-4">
        <div class="row g-2" style="max-width:360px">
          <div class="col">
            <label class="form-label small mb-1">Peticiones/seg por IP</label>
            <input v-model.number="form.rate_limit_rps" type="number" min="1" max="1000"
                   class="form-control form-control-sm" />
          </div>
          <div class="col">
            <label class="form-label small mb-1">Ráfaga tolerada</label>
            <input v-model.number="form.rate_limit_burst" type="number" min="0" max="1000"
                   class="form-control form-control-sm" />
          </div>
        </div>
        <div class="form-text">
          Si una IP supera el ritmo, NGINX responde 429. Protege ante ataques o scripts abusivos
          sin afectar al tráfico normal. Ej: 10 req/s, ráfaga 20.
        </div>
      </div>

      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">Seguridad PHP</p>

      <div class="mb-2 form-check">
        <input id="php_hardening" v-model="form.php_hardening_relaxed" type="checkbox" class="form-check-input" />
        <label for="php_hardening" class="form-check-label">
          <i class="bi bi-terminal me-1"></i> Permitir funciones de sistema (exec, shell_exec…)
        </label>
      </div>
      <div class="form-text ps-4">
        Por seguridad, este dominio bloquea funciones PHP peligrosas (exec, system, shell_exec,
        passthru, proc_open, popen) que usan la mayoría de los malware. Actívalo solo si una
        aplicación legítima las necesita. El aislamiento del sitio (open_basedir) se mantiene
        siempre. Afecta únicamente a este dominio.
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

    <!-- ── Sección SSL (solo en edición) ─────────────────────────────────── -->
    <template v-if="isEditing">
      <hr class="my-3" />
      <p class="fw-semibold mb-2 text-muted small text-uppercase">
        <i class="bi bi-shield-lock me-1"></i> SSL / HTTPS
      </p>

      <div class="mb-2 form-check">
        <input id="ssl_enabled" v-model="ssl.enabled" type="checkbox" class="form-check-input" />
        <label for="ssl_enabled" class="form-check-label">
          Habilitar SSL (Let's Encrypt) para este dominio
        </label>
      </div>

      <div class="ps-4">
        <template v-if="ssl.enabled">
          <div class="mb-2 form-check">
            <input id="force_https" v-model="ssl.force_https" type="checkbox" class="form-check-input" />
            <label for="force_https" class="form-check-label">
              Redirección automática HTTP → HTTPS
            </label>
          </div>
          <div class="mb-3 form-check">
            <input id="hsts_enabled" v-model="ssl.hsts_enabled" type="checkbox" class="form-check-input" />
            <label for="hsts_enabled" class="form-check-label">
              Activar HSTS <small class="text-muted">(Strict-Transport-Security)</small>
            </label>
          </div>

          <!-- Email para certbot si no hay certificado aún -->
          <div class="mb-3" v-if="!ssl.cert_info">
            <label class="form-label small">Email para Let's Encrypt <span class="text-danger">*</span></label>
            <input v-model="ssl.email" type="email" class="form-control form-control-sm"
              placeholder="admin@ejemplo.com" />
          </div>

          <!-- Info del certificado existente -->
          <div v-if="ssl.cert_info" class="mb-3">
            <ul class="list-unstyled small bg-light rounded p-2 mb-1">
              <li><strong>Expedido a:</strong> {{ ssl.cert_info.issued_to }}</li>
              <li v-if="ssl.cert_info.sans?.length">
                <strong>SANs:</strong> {{ ssl.cert_info.sans.join(', ') }}
              </li>
              <li><strong>Válido desde:</strong> {{ ssl.cert_info.not_before }}</li>
              <li><strong>Válido hasta:</strong>
                <span :class="isCertExpiringSoon(ssl.cert_info.not_after) ? 'text-danger fw-semibold' : ''">
                  {{ ssl.cert_info.not_after }}
                </span>
              </li>
              <li><strong>Algoritmo:</strong> {{ ssl.cert_info.signature_alg }}</li>
              <li v-if="ssl.cert_info.key_size"><strong>Tamaño clave:</strong> {{ ssl.cert_info.key_size }} bits</li>
              <li><strong>Emisor:</strong> {{ ssl.cert_info.issuer }}</li>
            </ul>
            <button type="button" class="btn btn-link btn-sm p-0 text-secondary"
              @click="ssl.showCert = !ssl.showCert">
              {{ ssl.showCert ? 'Ocultar certificado PEM' : 'Mostrar certificado PEM' }}
            </button>
            <pre v-if="ssl.showCert"
              class="mt-2 small bg-dark text-light p-2 rounded"
              style="max-height:200px;overflow:auto;white-space:pre-wrap;">{{ ssl.cert_info.pem }}</pre>
          </div>
        </template>

        <div class="d-flex gap-2 flex-wrap">
          <button v-if="ssl.enabled || ssl.cert_info" type="button" class="btn btn-sm"
            :class="ssl.enabled ? 'btn-success' : 'btn-outline-danger'"
            @click="applySSL" :disabled="sslLoading">
            <span v-if="sslLoading" class="spinner-border spinner-border-sm me-1"></span>
            <template v-if="ssl.enabled">
              {{ ssl.cert_info ? 'Actualizar SSL' : "Activar SSL (Let's Encrypt)" }}
            </template>
            <template v-else>Desactivar SSL</template>
          </button>
          <span v-if="sslMessage" :class="sslError ? 'text-danger small align-self-center' : 'text-success small align-self-center'">
            {{ sslMessage }}
          </span>
        </div>
      </div>
    </template>
    <!-- ── Fin sección SSL ────────────────────────────────────────────────── -->

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

const TEMPLATE_CATEGORIES = [
  { key: 'cms',        label: 'CMS' },
  { key: 'framework',  label: 'Frameworks' },
  { key: 'ecommerce',  label: 'E-commerce' },
  { key: 'other',      label: 'Otros' },
]

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
    const templates  = ref([])
    const serverIps  = ref([])

    const isAdminOrReseller = computed(() =>
      ['admin', 'reseller'].includes(store.currentUser?.role)
    )

    // Versiones disponibles: usa las del padre si las pasa, si no carga propias
    const availablePhpVersions = computed(() =>
      props.phpVersions.length ? props.phpVersions : localPhpVersions.value
    )

    const form = ref({
      domain_name: props.domain?.domain_name || '',
      user_id:     props.domain?.user_id     || (isAdminOrReseller.value ? '' : store.currentUser?.id),
      php_version: props.domain?.php_version || '',
      is_active:   props.domain?.is_active   ?? true,
      fastcgi_cache_enabled:     props.domain?.fastcgi_cache_enabled     ?? false,
      fastcgi_cache_ttl_minutes: props.domain?.fastcgi_cache_ttl_minutes ?? 60,
      rate_limit_enabled: props.domain?.rate_limit_enabled ?? false,
      rate_limit_rps:     props.domain?.rate_limit_rps     ?? 10,
      rate_limit_burst:   props.domain?.rate_limit_burst   ?? 20,
      php_hardening_relaxed: props.domain?.php_hardening_relaxed ?? false,
      dns_enabled:  false,
      mail_enabled: false,
      selected_template_id: props.domain?.applied_template_id ?? null,
      // Redirección y docroot (Fase 16)
      redirect_enabled: !!(props.domain?.redirect_to),
      redirect_to:      props.domain?.redirect_to    || '',
      custom_docroot:   props.domain?.custom_docroot || '',
      // IPv4 dedicada
      ipv4: props.domain?.ipv4 || null,
      // IPv6 (solo en creación, opcional)
      ipv6: props.domain?.ipv6 || null,
    })

    const redirectError = ref('')
    const docrootError  = ref('')

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
      // Validaciones de redirección y docroot antes de enviar
      redirectError.value = ''
      docrootError.value  = ''

      if (isEditing.value) {
        if (form.value.redirect_enabled) {
          const url = form.value.redirect_to.trim()
          if (!url) {
            redirectError.value = 'Introduce la URL de destino.'
            return
          }
          if (!/^https?:\/\//i.test(url)) {
            redirectError.value = 'La URL debe empezar por http:// o https://'
            return
          }
        }
        if (!form.value.redirect_enabled && form.value.custom_docroot.trim()) {
          const dr = form.value.custom_docroot.trim()
          if (!dr.startsWith('/')) {
            docrootError.value = 'Debe ser una ruta absoluta (empieza por /).'
            return
          }
          if (dr.includes('..')) {
            docrootError.value = 'La ruta no puede contener "..".'
            return
          }
        }
      }

      loading.value = true
      try {
        if (isEditing.value) {
          await api.updateDomain(props.domain.id, {
            php_version: form.value.php_version,
            is_active:   form.value.is_active,
            ipv4:        form.value.ipv4 || null,
            ipv6:        form.value.ipv6 || null,
            redirect_to:    form.value.redirect_enabled ? form.value.redirect_to.trim() : '',
            custom_docroot: !form.value.redirect_enabled ? form.value.custom_docroot.trim() : '',
          })
          // Caché FastCGI: solo si cambió y no se va a aplicar plantilla (la plantilla lo gestiona)
          const prevEnabled = props.domain.fastcgi_cache_enabled ?? false
          const prevTtl     = props.domain.fastcgi_cache_ttl_minutes ?? 60
          const cacheChanged =
            form.value.fastcgi_cache_enabled !== prevEnabled ||
            (form.value.fastcgi_cache_enabled && form.value.fastcgi_cache_ttl_minutes !== prevTtl)
          if (cacheChanged && !form.value.selected_template_id) {
            await api.setDomainCache(
              props.domain.id,
              form.value.fastcgi_cache_enabled,
              form.value.fastcgi_cache_ttl_minutes,
            )
          }
          // Rate limit: solo si cambió respecto al estado original (reescribe el vhost)
          const prevRl      = props.domain.rate_limit_enabled ?? false
          const prevRps     = props.domain.rate_limit_rps     ?? 10
          const prevBurst   = props.domain.rate_limit_burst   ?? 20
          const rlChanged =
            form.value.rate_limit_enabled !== prevRl ||
            (form.value.rate_limit_enabled &&
              (form.value.rate_limit_rps !== prevRps || form.value.rate_limit_burst !== prevBurst))
          if (rlChanged) {
            await api.setDomainRateLimit(
              props.domain.id,
              form.value.rate_limit_enabled,
              form.value.rate_limit_rps,
              form.value.rate_limit_burst,
            )
          }
          // Hardening PHP: solo si cambió (reescribe el pool + vhost)
          const prevHardening = props.domain.php_hardening_relaxed ?? false
          if (form.value.php_hardening_relaxed !== prevHardening) {
            await api.setDomainPhpHardening(
              props.domain.id,
              form.value.php_hardening_relaxed,
            )
          }
          // Aplicar plantilla si se seleccionó una (y es diferente a la actual)
          const prevTemplateId = props.domain?.applied_template_id ?? null
          if (form.value.selected_template_id && form.value.selected_template_id !== prevTemplateId) {
            await api.applyTemplate(props.domain.id, form.value.selected_template_id, {
              ttl_minutes: form.value.fastcgi_cache_ttl_minutes,
            })
            store.showNotification(
              `Plantilla "${selectedTemplate.value?.name}" aplicada correctamente`,
              'success'
            )
          } else {
            store.showNotification('Dominio actualizado correctamente', 'success')
          }
        } else {
          const userId = isAdminOrReseller.value
            ? form.value.user_id
            : store.currentUser?.id
          const created = await api.createDomain({
            domain_name:  form.value.domain_name,
            user_id:      userId,
            php_version:  form.value.php_version,
            is_active:    form.value.is_active,
            dns_enabled:  form.value.dns_enabled,
            mail_enabled: form.value.mail_enabled,
            ipv4:         form.value.ipv4 || null,
            ipv6:         form.value.ipv6 || null,
          })
          // Aplicar plantilla tras crear el dominio
          if (form.value.selected_template_id && created?.id) {
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

    // ── SSL ────────────────────────────────────────────────────────────────

    const ssl = ref({
      enabled:      props.domain?.ssl_enabled  ?? false,
      force_https:  props.domain?.force_https   ?? false,
      hsts_enabled: props.domain?.hsts_enabled  ?? false,
      email:        '',
      cert_info:    null,
      showCert:     false,
    })
    const sslLoading = ref(false)
    const sslMessage = ref('')
    const sslError   = ref(false)

    const loadSSL = async () => {
      if (!props.domain?.id) return
      try {
        const data = await api.getDomainSSL(props.domain.id)
        ssl.value.enabled      = data.ssl_enabled      ?? ssl.value.enabled
        ssl.value.force_https  = data.force_https      ?? ssl.value.force_https
        ssl.value.hsts_enabled = data.hsts_enabled     ?? ssl.value.hsts_enabled
        ssl.value.cert_info    = data.cert_info        || null
      } catch { /* silencioso */ }
    }

    const isCertExpiringSoon = (dateStr) => {
      if (!dateStr) return false
      const expDate = new Date(dateStr)
      const now = new Date()
      const diffDays = (expDate - now) / (1000 * 60 * 60 * 24)
      return diffDays < 15
    }

    const applySSL = async () => {
      sslMessage.value = ''
      sslError.value   = false
      sslLoading.value = true
      try {
        const payload = {
          enabled:      ssl.value.enabled,
          force_https:  ssl.value.force_https,
          hsts_enabled: ssl.value.hsts_enabled,
        }
        if (ssl.value.enabled && !ssl.value.cert_info && ssl.value.email) {
          payload.email = ssl.value.email
        }
        await api.toggleDomainSSL(props.domain.id, payload)
        sslMessage.value = ssl.value.enabled ? 'SSL activado correctamente.' : 'SSL desactivado.'
        // Recargar info del cert
        await loadSSL()
      } catch (e) {
        sslError.value   = true
        sslMessage.value = 'Error: ' + (e.message || 'No se pudo aplicar SSL')
      } finally {
        sslLoading.value = false
      }
    }

    onMounted(async () => {
      await Promise.all([loadUsers(), loadPHPVersions(), loadTemplates(), loadServerIps()])
      if (isEditing.value) loadSSL()
      // Si la versión guardada no está en la lista, seleccionar la primera disponible
      if (form.value.php_version && !availablePhpVersions.value.includes(form.value.php_version)) {
        form.value.php_version = availablePhpVersions.value[0] || '8.2'
      } else if (!form.value.php_version && availablePhpVersions.value.length) {
        form.value.php_version = availablePhpVersions.value[0]
      }
    })

    return {
      form, loading, isEditing, users,
      isAdminOrReseller, availablePhpVersions,
      templates, templateCategories, templatesByCategory,
      selectedTemplate, parsedPhpOverrides,
      serverIps, ipv6Enabled, ipv6Suggestions, ipv6Loading, _uid,
      redirectError, docrootError,
      handleSubmit,
      // SSL
      ssl, sslLoading, sslMessage, sslError,
      applySSL, isCertExpiringSoon,
    }
  }
}
</script>
