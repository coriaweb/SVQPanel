<template>
  <div class="sv-view mig">
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Migrar desde otro panel</h1>
        <p class="page-head__sub">Importa un backup de HestiaCP o cPanel y recrea sus webs, bases de datos, correo y DNS en SVQPanel.</p>
      </div>
    </div>

    <!-- Paso 1: origen + destino -->
    <BaseCard title="1 · Origen del backup y destino" icon="box-arrow-in-down">
      <div class="mig-grid">
        <label class="mig-field">
          <span>Panel de origen</span>
          <select class="svq-select" v-model="sourcePanel">
            <option value="hestia">HestiaCP</option>
            <option value="cpanel">cPanel</option>
          </select>
        </label>
        <label class="mig-field">
          <span>Origen</span>
          <select class="svq-select" v-model="source">
            <option value="upload">Subir archivo .tar</option>
            <option value="path">Ruta en el servidor</option>
            <option value="url">Descargar desde URL</option>
            <option value="ssh">SSH al servidor Hestia</option>
          </select>
        </label>

        <label class="mig-field" v-if="source === 'upload'">
          <span>Archivo de backup ({{ sourcePanel === 'cpanel' ? '.tar.gz' : '.tar' }})</span>
          <input type="file" accept=".tar,.gz,.tgz" class="svq-input" @change="onFile" />
        </label>
        <label class="mig-field" v-else-if="source === 'path'">
          <span>Ruta del .tar en el servidor</span>
          <input class="svq-input mono" v-model="serverPath" placeholder="/backups/usuario.YYYY-MM-DD.tar" />
        </label>
        <label class="mig-field" v-else-if="source === 'url'">
          <span>URL del backup (.tar)</span>
          <input class="svq-input mono" v-model="url" placeholder="https://servidor/backup/usuario.tar" />
        </label>
      </div>

      <p class="mig-hint dd-muted">
        <i class="bi bi-info-circle"></i>
        <template v-if="sourcePanel === 'cpanel'">
          Backup completo de cPanel (cpmove). En cPanel: <strong>Archivos → Copia de seguridad → Descargar una copia de seguridad completa</strong>, o por terminal <code>/scripts/pkgacct usuario</code>. El archivo es un <code>.tar.gz</code> que empieza por <code>cpmove-</code> o <code>backup-</code>.
        </template>
        <template v-else>
          Backup de usuario de HestiaCP. En el servidor Hestia: <code>v-backup-user usuario</code> (queda en <code>/backup/</code>), o con el origen «SSH» el panel lo genera y lo trae solo.
        </template>
      </p>

      <!-- Campos SSH (origen = ssh) -->
      <div v-if="source === 'ssh'" class="mig-grid mig-ssh">
        <label class="mig-field"><span>Host del Hestia origen</span>
          <input class="svq-input mono" v-model="ssh.host" placeholder="1.2.3.4" /></label>
        <label class="mig-field"><span>Usuario SSH</span>
          <input class="svq-input mono" v-model="ssh.user" placeholder="root" /></label>
        <label class="mig-field"><span>Puerto SSH</span>
          <input class="svq-input mono" v-model="ssh.port" placeholder="22" /></label>
        <label class="mig-field"><span>Usuario de Hestia a exportar</span>
          <input class="svq-input mono" v-model="ssh.hestia_user" placeholder="cliente1" /></label>
        <label class="mig-field"><span>Contraseña SSH (o usa clave)</span>
          <input type="password" class="svq-input" v-model="ssh.password" /></label>
        <label class="mig-field mig-field--wide"><span>Clave privada SSH (opcional)</span>
          <textarea class="svq-input mono" rows="3" v-model="ssh.key" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea></label>
      </div>

      <div class="mig-grid">
        <label class="mig-field">
          <span>Cliente destino</span>
          <select class="svq-select" v-model="targetUserId">
            <option :value="null" disabled>Elige un cliente…</option>
            <option v-for="u in clientUsers" :key="u.id" :value="u.id">{{ u.username }} ({{ u.email }})</option>
          </select>
        </label>
      </div>

      <div class="mig-scope">
        <span class="mig-scope__label">Importar:</span>
        <label v-for="s in scopeOptions" :key="s.key" class="mig-check">
          <input type="checkbox" v-model="scope" :value="s.key" /> {{ s.label }}
        </label>
      </div>

      <div class="mig-actions">
        <BaseButton variant="primary" icon="search" :loading="analyzing" :disabled="!canAnalyze" @click="analyze">Analizar backup</BaseButton>
        <small class="dd-muted">El análisis no modifica nada del servidor.</small>
      </div>
    </BaseCard>

    <!-- Paso 2: manifiesto -->
    <BaseCard v-if="manifest" title="2 · Contenido del backup" icon="list-check">
      <div v-if="manifest.warnings && manifest.warnings.length" class="mig-warn">
        <i class="bi bi-exclamation-triangle"></i>
        <div><div v-for="(w,i) in manifest.warnings" :key="i">{{ w }}</div></div>
      </div>

      <div class="mig-summary">
        <div class="mig-stat"><span class="mig-stat__n">{{ manifest.web.length }}</span><span class="mig-stat__k">Webs</span></div>
        <div class="mig-stat"><span class="mig-stat__n">{{ manifest.db.length }}</span><span class="mig-stat__k">Bases de datos</span></div>
        <div class="mig-stat"><span class="mig-stat__n">{{ mailAccounts }}</span><span class="mig-stat__k">Buzones</span></div>
        <div class="mig-stat"><span class="mig-stat__n">{{ manifest.dns.length }}</span><span class="mig-stat__k">Zonas DNS</span></div>
      </div>

      <div class="mig-lists">
        <div v-if="manifest.web.length">
          <h4 class="mig-h">Webs</h4>
          <ul class="mig-ul">
            <li v-for="w in manifest.web" :key="w.domain">
              <strong>{{ w.domain }}</strong> · PHP {{ w.php_version || '—' }}
              <span v-if="w.ssl" class="mig-tag">SSL</span>
              <span v-if="!w.has_data" class="mig-tag mig-tag--muted">sin archivos</span>
            </li>
          </ul>
        </div>
        <div v-if="manifest.db.length">
          <h4 class="mig-h">Bases de datos</h4>
          <ul class="mig-ul">
            <li v-for="d in manifest.db" :key="d.db"><strong>{{ d.db }}</strong> · {{ d.type }}<span v-if="!d.has_dump" class="mig-tag mig-tag--muted">sin dump</span></li>
          </ul>
        </div>
        <div v-if="manifest.mail.length">
          <h4 class="mig-h">Correo</h4>
          <ul class="mig-ul">
            <li v-for="m in manifest.mail" :key="m.domain"><strong>{{ m.domain }}</strong> · {{ m.accounts_count }} buzón(es)</li>
          </ul>
        </div>
        <div v-if="manifest.dns.length">
          <h4 class="mig-h">DNS</h4>
          <ul class="mig-ul">
            <li v-for="z in manifest.dns" :key="z.domain"><strong>{{ z.domain }}</strong> · {{ z.records_count }} registro(s)</li>
          </ul>
        </div>
      </div>

      <!-- Revisión de zonas DNS (tabla editable) -->
      <div v-if="manifest.dns.length && scope.includes('dns')" class="mig-dns">
        <div class="mig-dnsnote">
          <i class="bi bi-info-circle"></i>
          Los <strong>NS</strong> y el <strong>SOA</strong> los genera SVQPanel (nameservers del panel) — recuerda delegar el dominio a ns1/ns2 de SVQPanel.
          Los registros <strong>A</strong> que apuntaban al servidor antiguo ({{ dnsZones[0]?.old_ip || 'IP vieja' }}) se reescriben a este servidor ({{ dnsZones[0]?.server_ipv4 || '' }}); el resto se mantiene. Revisa y ajusta lo que quieras.
        </div>

        <div v-for="z in dnsZones" :key="'dz'+z.domain" class="mig-dnszone">
          <button class="mig-dnshdr" @click="z._open = !z._open">
            <i class="bi" :class="z._open ? 'bi-chevron-down' : 'bi-chevron-right'"></i>
            <strong>{{ z.domain }}</strong>
            <span class="dd-muted">· {{ z.records.filter(r => r.include).length }}/{{ z.records.length }} a importar</span>
          </button>
          <div v-if="z._open" class="mig-dnstbl-wrap">
            <table class="mig-table mig-dnstbl">
              <thead><tr><th></th><th>Nombre</th><th>Tipo</th><th>Valor</th><th>TTL</th><th>Acción</th></tr></thead>
              <tbody>
                <tr v-for="(r,ri) in z.records" :key="ri" :class="{ 'is-discard': r.type==='NS'||r.type==='SOA', 'is-off': !r.include }">
                  <td><input type="checkbox" v-model="r.include" :disabled="r.type==='NS'||r.type==='SOA'" /></td>
                  <td class="mono">{{ r.name }}</td>
                  <td>{{ r.type }}</td>
                  <td>
                    <template v-if="r.type==='NS'||r.type==='SOA'"><span class="dd-muted mono">{{ r.content }}</span></template>
                    <template v-else-if="r.action==='rewrite'">
                      <input class="svq-input mono mig-dnsinput" v-model="r.new_content" />
                      <span class="mig-old">antes: {{ r.original_content }}</span>
                    </template>
                    <input v-else class="svq-input mono mig-dnsinput" v-model="r.content" />
                  </td>
                  <td><input class="svq-input mono mig-dnsttl" v-model.number="r.ttl" :disabled="r.type==='NS'||r.type==='SOA'" /></td>
                  <td>
                    <span v-if="r.type==='NS'||r.type==='SOA'" class="mig-badge mig-badge--discard">descartado</span>
                    <span v-else-if="r.action==='rewrite'" class="mig-badge mig-badge--rewrite" :title="r.note">reescrito → SVQ</span>
                    <span v-else class="mig-badge mig-badge--keep" :title="r.note">se mantiene</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Conflictos: bloquean la importación -->
      <div v-if="manifest.conflicts.length" class="mig-conflicts">
        <p class="mig-conflicts__title"><i class="bi bi-x-octagon-fill"></i> No se puede importar: hay recursos que ya existen</p>
        <ul><li v-for="(c,i) in manifest.conflicts" :key="i">{{ c }}</li></ul>
        <small class="dd-muted">Elimina esos recursos en SVQPanel (o cámbialos en el backup) y vuelve a analizar.</small>
      </div>

      <div class="mig-actions" v-else>
        <BaseButton variant="primary" icon="box-arrow-in-down" :loading="importing" @click="startImport">Importar a «{{ targetUsername }}»</BaseButton>
        <small class="dd-muted">Esto creará los recursos en el servidor. Las contraseñas se conservan cuando es posible.</small>
      </div>
    </BaseCard>

    <!-- Paso 3: progreso / informe -->
    <BaseCard v-if="job" title="3 · Importación" icon="hourglass-split">
      <div v-if="job.status === 'pending' || job.status === 'running'" class="mig-running">
        <span class="spinner"></span> Importando… ({{ job.status }}). Esto puede tardar varios minutos.
      </div>
      <div v-else-if="job.status === 'failed' && !job.report" class="mig-error">
        <i class="bi bi-x-circle"></i> La importación falló: {{ job.error }}
      </div>
      <div v-else-if="job.report">
        <div class="mig-report-head" :class="job.status === 'success' ? 'is-ok' : 'is-warn'">
          <i :class="job.status === 'success' ? 'bi bi-check-circle-fill' : 'bi bi-exclamation-triangle-fill'"></i>
          {{ job.report.summary.created }} creados ·
          {{ job.report.summary.errors }} errores ·
          {{ job.report.summary.new_passwords }} contraseñas nuevas
        </div>

        <table v-if="job.report.created.length" class="mig-table">
          <thead><tr><th>Tipo</th><th>Recurso</th><th>Detalle</th></tr></thead>
          <tbody>
            <tr v-for="(c,i) in job.report.created" :key="'c'+i"><td>{{ c.type }}</td><td class="mono">{{ c.name }}</td><td class="dd-muted">{{ c.detail }}</td></tr>
          </tbody>
        </table>

        <div v-if="job.report.passwords.length" class="mig-pw">
          <h4 class="mig-h"><i class="bi bi-key"></i> Contraseñas nuevas (cópialas, no se vuelven a mostrar)</h4>
          <table class="mig-table">
            <thead><tr><th>Tipo</th><th>Recurso</th><th>Contraseña</th></tr></thead>
            <tbody>
              <tr v-for="(p,i) in job.report.passwords" :key="'p'+i"><td>{{ p.type }}</td><td class="mono">{{ p.name }}</td><td class="mono mig-pwval">{{ p.password }}</td></tr>
            </tbody>
          </table>
        </div>

        <div v-if="job.report.errors.length" class="mig-errs">
          <h4 class="mig-h">Errores</h4>
          <ul><li v-for="(e,i) in job.report.errors" :key="'e'+i"><span class="mono">{{ e.name }}</span>: {{ e.error }}</li></ul>
        </div>
      </div>
    </BaseCard>
  </div>
</template>

<script>
import { ref, computed, onUnmounted } from 'vue'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'

export default {
  name: 'Migrations',
  components: { BaseCard, BaseButton },
  setup() {
    const store = useMainStore()
    const sourcePanel = ref('hestia')
    const source = ref('upload')
    const file = ref(null)
    const serverPath = ref('')
    const url = ref('')
    const ssh = ref({ host: '', user: 'root', port: '22', hestia_user: '', password: '', key: '' })
    const targetUserId = ref(null)
    const clientUsers = ref([])
    const scope = ref(['web', 'db', 'mail', 'dns'])
    const scopeOptions = [
      { key: 'web', label: 'Webs' }, { key: 'db', label: 'Bases de datos' },
      { key: 'mail', label: 'Correo' }, { key: 'dns', label: 'DNS' },
    ]
    const analyzing = ref(false)
    const importing = ref(false)
    const manifest = ref(null)
    const dnsZones = ref([])   // zonas DNS con registros editables (clon de proposed_records)
    const job = ref(null)
    let pollTimer = null

    const canAnalyze = computed(() => {
      if (targetUserId.value == null) return false
      if (source.value === 'upload') return !!file.value
      if (source.value === 'path') return !!serverPath.value.trim()
      if (source.value === 'url') return !!url.value.trim()
      if (source.value === 'ssh') return !!ssh.value.host.trim() && !!ssh.value.hestia_user.trim()
      return false
    })
    const mailAccounts = computed(() =>
      (manifest.value?.mail || []).reduce((n, m) => n + (m.accounts_count || 0), 0))
    const targetUsername = computed(() =>
      clientUsers.value.find(u => u.id === targetUserId.value)?.username || '')

    const loadUsers = async () => {
      try {
        const r = await api.getUsers(0, 200)
        const list = Array.isArray(r) ? r : (r.users || r.data || [])
        clientUsers.value = list.filter(u => !(u.is_admin || u.role === 'admin'))
      } catch (e) { store.showNotification('No pude cargar los usuarios', 'danger') }
    }

    const onFile = (e) => { file.value = e.target.files?.[0] || null }

    const _formData = (forImport = false) => {
      const fd = new FormData()
      if (source.value === 'upload' && file.value) fd.append('file', file.value)
      else if (source.value === 'path') fd.append('path', serverPath.value.trim())
      else if (source.value === 'url') fd.append('url', url.value.trim())
      else if (source.value === 'ssh') {
        fd.append('ssh_host', ssh.value.host.trim())
        fd.append('ssh_user', ssh.value.user.trim() || 'root')
        if (ssh.value.port) fd.append('ssh_port', String(ssh.value.port).trim())
        fd.append('hestia_user', ssh.value.hestia_user.trim())
        if (ssh.value.password) fd.append('ssh_password', ssh.value.password)
        if (ssh.value.key) fd.append('ssh_key', ssh.value.key)
      }
      fd.append('target_user_id', String(targetUserId.value))
      fd.append('scope', scope.value.join(','))
      fd.append('source_panel', sourcePanel.value)
      // En la importación, enviar los registros DNS aprobados/editados.
      if (forImport && scope.value.includes('dns') && dnsZones.value.length) {
        const payload = {}
        for (const z of dnsZones.value) payload[z.domain] = z.records
        fd.append('dns_records', JSON.stringify(payload))
      }
      return fd
    }

    const analyze = async () => {
      analyzing.value = true; manifest.value = null; job.value = null; dnsZones.value = []
      try {
        const r = await api.hestiaAnalyze(_formData())
        manifest.value = r.data
        // Clonar las zonas DNS para edición local (registros + estado abierto).
        dnsZones.value = (r.data.dns || []).map((z, i) => ({
          domain: z.domain,
          old_ip: z.old_ip,
          server_ipv4: z.server_ipv4,
          _open: i === 0,   // la primera abierta por defecto
          records: (z.proposed_records || []).map(rec => ({ ...rec })),
        }))
      } catch (e) {
        store.showNotification('Error analizando: ' + e.message, 'danger')
      } finally { analyzing.value = false }
    }

    const startImport = async () => {
      if (!confirm(`¿Importar el backup a la cuenta «${targetUsername.value}»? Se crearán los recursos en el servidor.`)) return
      importing.value = true
      try {
        const r = await api.hestiaImport(_formData(true))
        const jobId = r.data.job_id
        job.value = { status: 'pending', report: null }
        _poll(jobId)
      } catch (e) {
        if (e.status === 409 && Array.isArray(e.data?.conflicts)) {
          store.showNotification('Importación cancelada por conflictos', 'danger')
          manifest.value = { ...manifest.value, conflicts: e.data.conflicts }
        } else {
          store.showNotification('Error al importar: ' + e.message, 'danger')
        }
      } finally { importing.value = false }
    }

    const _poll = (jobId) => {
      const tick = async () => {
        try {
          const r = await api.getMigrationJob(jobId)
          job.value = r.data
          if (r.data.status === 'pending' || r.data.status === 'running') {
            pollTimer = setTimeout(tick, 2500)
          }
        } catch (e) { /* reintenta */ pollTimer = setTimeout(tick, 4000) }
      }
      tick()
    }

    onUnmounted(() => { if (pollTimer) clearTimeout(pollTimer) })
    loadUsers()

    return {
      sourcePanel, source, file, serverPath, url, ssh, targetUserId, clientUsers, scope, scopeOptions,
      analyzing, importing, manifest, dnsZones, job, canAnalyze, mailAccounts, targetUsername,
      onFile, analyze, startImport,
    }
  },
}
</script>

<style scoped>
/* Inputs/selects con la estética SVQ (mismas variables que el resto del panel).
   Se definen aquí porque .svq-input/.svq-select viven scoped en cada vista. */
.svq-select, .svq-input {
  height: 38px; padding: 0 var(--sp-3); width: 100%;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-md); font-size: var(--fs-base);
}
.svq-select { cursor: pointer; }
.svq-input:focus, .svq-select:focus { outline: none; border-color: var(--color-primary); box-shadow: var(--shadow-focus); }
textarea.svq-input { height: auto; padding: var(--sp-2) var(--sp-3); line-height: 1.4; }
input[type="file"].svq-input { padding: var(--sp-2); height: auto; }

/* Igual que el resto de vistas: ocupa el ancho del área de contenido. Las
   tarjetas se separan en vertical. */
.mig :deep(.card) { margin-bottom: var(--sp-4); }
.mig-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--sp-3); }
.mig-field { display: flex; flex-direction: column; gap: 4px; }
.mig-field > span { font-size: var(--fs-sm); color: var(--text-secondary); font-weight: var(--fw-medium); }
.mig-field--wide { grid-column: 1 / -1; }
.mig-ssh { margin-top: var(--sp-3); padding-top: var(--sp-3); border-top: 1px solid var(--border); }
.mig-ssh textarea { resize: vertical; }
.mig-scope { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; margin-top: var(--sp-3); }
.mig-scope__label { font-size: var(--fs-sm); color: var(--text-muted); }
.mig-check { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-sm); }
.mig-actions { display: flex; align-items: center; gap: var(--sp-3); margin-top: var(--sp-4); flex-wrap: wrap; }
.mig-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-3); margin-bottom: var(--sp-4); }
.mig-stat { background: var(--surface-inset); border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--sp-3); text-align: center; }
.mig-stat__n { display: block; font-size: 1.6rem; font-weight: var(--fw-bold); color: var(--svq-orange); }
.mig-stat__k { font-size: var(--fs-xs); text-transform: uppercase; color: var(--text-muted); }
.mig-lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--sp-4); }
.mig-h { font-size: var(--fs-sm); text-transform: uppercase; color: var(--text-muted); margin: 0 0 6px; }
.mig-ul { margin: 0; padding-left: 1.1rem; font-size: var(--fs-sm); }
.mig-ul li { margin-bottom: 4px; }
.mig-tag { font-size: .68rem; padding: 1px 6px; border-radius: 999px; background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); margin-left: 4px; }
.mig-tag--muted { background: var(--surface-inset); color: var(--text-muted); }
.mig-warn { display: flex; gap: .5rem; padding: .6rem .8rem; border-radius: var(--radius-md); background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--warning); margin-bottom: var(--sp-3); font-size: var(--fs-sm); }
.mig-conflicts { margin-top: var(--sp-4); padding: var(--sp-3); border: 1px solid var(--danger); border-radius: var(--radius-md); background: color-mix(in srgb, var(--danger) 8%, transparent); }
.mig-conflicts__title { color: var(--danger); font-weight: var(--fw-semibold); margin: 0 0 6px; display: flex; align-items: center; gap: 6px; }
.mig-running, .mig-error { display: flex; align-items: center; gap: .5rem; padding: .5rem 0; }
.mig-error { color: var(--danger); }
.mig-report-head { display: flex; align-items: center; gap: .5rem; font-weight: var(--fw-semibold); margin-bottom: var(--sp-3); padding: .5rem .8rem; border-radius: var(--radius-md); }
.mig-report-head.is-ok { background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success); }
.mig-report-head.is-warn { background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--warning); }
.mig-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); margin-bottom: var(--sp-3); }
.mig-table th { text-align: left; font-size: .7rem; text-transform: uppercase; color: var(--text-muted); padding: 4px 8px; border-bottom: 1px solid var(--border); }
.mig-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.mig-pwval { color: var(--svq-orange); font-weight: 600; }
.mig-pw { margin-top: var(--sp-3); }
.mig-errs { margin-top: var(--sp-3); font-size: var(--fs-sm); color: var(--danger); }
.mono { font-family: var(--font-mono, monospace); }

/* Revisión DNS */
.mig-dns { margin-top: var(--sp-4); padding-top: var(--sp-4); border-top: 1px solid var(--border); }
.mig-dnsnote { display: flex; gap: .5rem; padding: .6rem .8rem; border-radius: var(--radius-md); background: var(--surface-inset); color: var(--text-secondary); font-size: var(--fs-sm); margin-bottom: var(--sp-3); }
.mig-dnszone { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: var(--sp-3); overflow: hidden; }
.mig-dnshdr { width: 100%; display: flex; align-items: center; gap: .5rem; padding: .6rem .8rem; background: var(--surface-inset); border: none; cursor: pointer; color: var(--text); font-size: var(--fs-base); text-align: left; }
.mig-dnshdr:hover { background: var(--surface-2); }
.mig-dnstbl-wrap { overflow-x: auto; }
.mig-dnstbl td { vertical-align: middle; }
.mig-dnstbl tr.is-discard { opacity: .6; }
.mig-dnstbl tr.is-off { opacity: .45; }
.mig-dnsinput { height: 30px; min-width: 200px; display: inline-block; }
.mig-dnsttl { height: 30px; width: 80px; }
.mig-old { display: block; font-size: .7rem; color: var(--text-muted); margin-top: 2px; }
.mig-badge { font-size: .68rem; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.mig-badge--keep { background: var(--surface-inset); color: var(--text-secondary); }
.mig-badge--rewrite { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.mig-badge--discard { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
</style>
