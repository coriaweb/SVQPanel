<template>
  <div class="svqm">
    <p class="svqm-beta">
      <i class="bi bi-cone-striped"></i>
      <strong>Beta.</strong> Trae una cuenta entera desde otro servidor con SVQPanel: la recrea aquí con las mismas
      contraseñas, copia webs, correo y bases de datos, y el DNS no cambia hasta que pulses «Corte».
      El servidor de origen necesita SVQPanel 0.279.0 o superior y acceso SSH como root.
    </p>

    <div class="svqm-grid">
      <label class="svqm-field"><span>Servidor SVQPanel de origen</span>
        <input class="svq-input mono" v-model="src.host" placeholder="203.0.113.10" /></label>
      <label class="svqm-field"><span>Usuario SSH</span>
        <input class="svq-input mono" v-model="src.ssh_user" placeholder="root" /></label>
      <label class="svqm-field"><span>Puerto SSH</span>
        <input class="svq-input mono" v-model.number="src.port" placeholder="22" /></label>
      <label class="svqm-field"><span>Cliente a traer (usuario en el origen)</span>
        <input class="svq-input mono" v-model="src.username" placeholder="cliente1" /></label>
      <label class="svqm-field"><span>Contraseña SSH (o usa clave)</span>
        <input type="password" class="svq-input" v-model="src.password" autocomplete="off" /></label>
      <label class="svqm-field svqm-field--wide"><span>Clave privada SSH (opcional)</span>
        <textarea class="svq-input mono" rows="3" v-model="src.key" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea></label>
    </div>

    <div class="svqm-actions">
      <BaseButton variant="primary" icon="search" :loading="analyzing" :disabled="!canAnalyze" @click="analyze">Analizar</BaseButton>
      <small class="dd-muted">Analizar no crea ni cambia nada en ningún servidor.</small>
    </div>

    <!-- Resultado del análisis -->
    <div v-if="plan" class="svqm-plan">
      <h4 class="svqm-h">Cuenta «{{ plan.summary.username }}» en {{ plan.source_hostname || src.host }}
        <small class="dd-muted">(SVQPanel {{ plan.source_version }})</small></h4>
      <div class="svqm-stats">
        <span><strong>{{ plan.summary.domains.length }}</strong> dominios</span>
        <span><strong>{{ plan.summary.mailboxes }}</strong> buzones</span>
        <span><strong>{{ plan.summary.databases.length }}</strong> BDs</span>
        <span><strong>{{ plan.summary.dns_zones }}</strong> zonas DNS</span>
        <span><strong>{{ plan.summary.crons }}</strong> crons</span>
        <span><strong>{{ plan.summary.ssl_certs }}</strong> certificados</span>
        <span v-if="plan.summary.home_bytes"><strong>{{ fmtBytes(plan.summary.home_bytes) }}</strong> en disco</span>
      </div>
      <div v-if="plan.conflicts.length" class="svqm-err">
        <i class="bi bi-x-octagon"></i>
        <div><strong>No se puede migrar todavía:</strong>
          <ul><li v-for="(c, i) in plan.conflicts" :key="'c' + i">{{ c }}</li></ul></div>
      </div>
      <div v-if="plan.warnings.length" class="svqm-warn">
        <i class="bi bi-exclamation-triangle"></i>
        <ul><li v-for="(w, i) in plan.warnings" :key="'w' + i">{{ w }}</li></ul>
      </div>
      <div class="svqm-actions">
        <BaseButton variant="primary" icon="cloud-arrow-down" :loading="starting"
                    :disabled="!plan.importable" @click="startImport">Migrar la cuenta</BaseButton>
        <small class="dd-muted">Crea la cuenta aquí y copia los datos. El DNS no se toca.</small>
      </div>
    </div>

    <!-- Trabajo en curso / último resultado -->
    <div v-if="job" class="svqm-job">
      <div v-if="job.status === 'pending' || job.status === 'running'" class="svqm-progress">
        <span class="spinner"></span>
        <span>{{ job.progress_detail || 'Preparando…' }}</span>
        <strong>{{ job.progress || 0 }}%</strong>
      </div>
      <div v-else-if="job.status === 'failed'" class="svqm-err">
        <i class="bi bi-x-circle"></i>
        <div>Falló: {{ job.error || 'ver errores' }}
          <ul v-if="job.report && job.report.errors"><li v-for="(e, i) in job.report.errors" :key="'je' + i">{{ e.type }} {{ e.name }}: {{ e.error }}</li></ul>
        </div>
      </div>
      <div v-else-if="job.report" class="svqm-ok">
        <i class="bi bi-check-circle"></i>
        <div>
          {{ job.report.summary ? job.report.summary.created : 0 }} elementos ·
          {{ job.report.summary ? job.report.summary.errors : 0 }} errores
          <span v-if="verifyOk === true"> · <strong>origen y destino coinciden</strong></span>
          <span v-else-if="verifyOk === false"> · <strong>hay diferencias</strong> (abajo)</span>
          <ul v-if="job.report.errors && job.report.errors.length">
            <li v-for="(e, i) in job.report.errors" :key="'re' + i">{{ e.type }} {{ e.name }}: {{ e.error }}</li>
          </ul>
          <ul v-if="diffs.length"><li v-for="(d, i) in diffs" :key="'d' + i">{{ d }}</li></ul>
        </div>
      </div>
    </div>

    <!-- Migraciones existentes y sus siguientes pasos -->
    <div v-if="migrations.length" class="svqm-list">
      <h4 class="svqm-h">Migraciones desde otro SVQPanel</h4>
      <table class="svqm-table">
        <thead><tr><th>Cuenta</th><th>Origen</th><th>Fase</th><th>Acciones</th></tr></thead>
        <tbody>
          <tr v-for="m in migrations" :key="m.id">
            <td class="mono">{{ m.username }}</td>
            <td class="mono">{{ m.host }}</td>
            <td>
              <span class="svqm-phase" :class="'is-' + m.phase">{{ phaseLabel(m) }}</span>
              <div v-if="m.ssl && !m.ssl.running && m.ssl.issued" class="dd-muted svqm-small">
                SSL: {{ m.ssl.issued.length }} emitidos<span v-if="m.ssl.waiting_dns && m.ssl.waiting_dns.length">,
                {{ m.ssl.waiting_dns.length }} esperando al DNS</span><span v-if="m.ssl.manual && m.ssl.manual.length">;
                correo/webmail: emitir desde Correo</span>
              </div>
            </td>
            <td class="svqm-btns">
              <template v-if="m.phase === 'imported'">
                <button class="mig-mini-btn" :disabled="m.busy" @click="resync(m)"><i class="bi bi-arrow-repeat"></i> Resincronizar</button>
                <button class="mig-mini-btn mig-mini-btn--danger" :disabled="m.busy" @click="cutover(m)"><i class="bi bi-signpost-split"></i> Corte DNS</button>
              </template>
              <template v-else-if="m.phase === 'cutover'">
                <button class="mig-mini-btn" :disabled="m.busy || (m.ssl && m.ssl.running)" @click="issueSsl(m)"><i class="bi bi-shield-lock"></i> Emitir Let's Encrypt</button>
                <button class="mig-mini-btn" :disabled="m.busy" @click="mailCatchup(m)"><i class="bi bi-envelope"></i> Recoger correo</button>
              </template>
              <span v-else-if="m.busy" class="dd-muted">en curso…</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="dd-muted svqm-small">
        <i class="bi bi-info-circle"></i>
        Antes del corte, prueba la web en el servidor nuevo (apuntando el dominio a esta IP en tu fichero hosts)
        y pulsa «Resincronizar» justo antes de cortar. Tras el corte ya no se resincroniza: el servidor nuevo
        es el bueno; «Recoger correo» trae el que aún llegue al viejo sin borrar nada. Los botones usan la
        contraseña SSH escrita arriba.
      </p>
    </div>
  </div>
</template>

<script>
import { ref, computed, onUnmounted } from 'vue'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseButton from './ui/BaseButton.vue'

export default {
  name: 'SvqMigration',
  components: { BaseButton },
  setup() {
    const store = useMainStore()
    const src = ref({ host: '', ssh_user: 'root', port: 22, username: '', password: '', key: '' })
    const plan = ref(null)
    const analyzing = ref(false)
    const starting = ref(false)
    const job = ref(null)
    const migrations = ref([])
    let timer = null

    const canAnalyze = computed(() => !!src.value.host.trim() && !!src.value.username.trim() &&
      (!!src.value.password || !!src.value.key.trim()))
    const creds = () => ({ password: src.value.password || null, key: src.value.key.trim() || null })
    const hasCreds = () => {
      if (src.value.password || src.value.key.trim()) return true
      store.showNotification('Escribe arriba la contraseña (o la clave) SSH del servidor de origen', 'warning')
      return false
    }
    const body = () => ({ ...src.value, host: src.value.host.trim(), username: src.value.username.trim(),
      port: Number(src.value.port) || 22, password: src.value.password || null, key: src.value.key.trim() || null })

    const fmtBytes = (b) => b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)} GB` : `${Math.round(b / 2 ** 20)} MB`
    const phaseLabel = (m) => {
      if (m.busy) return 'trabajando…'
      return { importing: 'importando', imported: 'copiada · DNS sin cambiar', cutover: 'corte hecho',
        failed: 'falló' }[m.phase] || m.phase
    }
    const verifyOk = computed(() => job.value?.report?.copy?.verify?.ok)
    const diffs = computed(() => {
      const v = job.value?.report?.copy?.verify
      if (!v) return []
      const out = []
      for (const w of v.web || []) if (!w.same) out.push(`web ${w.path}: ${w.src_files} ficheros en el origen, ${w.dst_files} aquí`)
      for (const d of v.db || []) for (const t of d.diff || []) out.push(`BD ${d.db}.${t.table}: ${t.src} filas en el origen, ${t.dst} aquí`)
      return out
    })

    const loadList = async () => {
      try { migrations.value = (await api.get('/api/migrations/svq')).data || [] } catch (e) { /* opcional */ }
    }
    const poll = (id) => {
      clearTimeout(timer)
      const tick = async () => {
        try {
          const r = await api.getMigrationJob(id)
          job.value = r.data
          if (r.data.status === 'pending' || r.data.status === 'running') { timer = setTimeout(tick, 2500); return }
          loadList()
        } catch (e) { timer = setTimeout(tick, 4000) }
      }
      tick()
    }

    const analyze = async () => {
      analyzing.value = true; plan.value = null
      try { plan.value = (await api.post('/api/migrations/svq/analyze', body())).data }
      catch (e) { store.showNotification('No se pudo analizar: ' + e.message, 'danger') }
      finally { analyzing.value = false }
    }
    const startImport = async () => {
      if (!confirm(`¿Migrar «${src.value.username}» desde ${src.value.host}? Se creará la cuenta aquí y se copiarán sus datos. El DNS no cambia.`)) return
      starting.value = true
      try {
        const r = await api.post('/api/migrations/svq/import', body())
        job.value = { status: 'pending' }
        poll(r.data.job_id); loadList()
      } catch (e) { store.showNotification('No se pudo empezar: ' + e.message, 'danger') }
      finally { starting.value = false }
    }
    const runJob = async (m, path, ask) => {
      if (!hasCreds() || (ask && !confirm(ask))) return
      try {
        const r = await api.post(`/api/migrations/svq/${m.id}/${path}`, creds())
        job.value = { status: 'pending' }
        poll(r.data.job_id); loadList()
      } catch (e) { store.showNotification(e.message, 'danger') }
    }
    const resync = (m) => runJob(m, 'resync', `¿Volver a copiar web, correo y BDs de «${m.username}» desde ${m.host}? Lo de aquí quedará igual que el origen.`)
    const mailCatchup = (m) => runJob(m, 'mail-catchup', null)
    const cutover = async (m) => {
      if (!confirm(`CORTE de «${m.username}»: se publican sus zonas DNS desde este servidor y las visitas y el correo empezarán a llegar aquí.\n\n¿Has resincronizado justo antes? Tras el corte ya no se puede resincronizar.`)) return
      const mark = confirm('¿Marcar la cuenta en el servidor de origen como «migrada» y pausar allí sus crons, backups y auto-update de WordPress? (No borra nada.)')
      if (mark && !hasCreds()) return
      try {
        const r = await api.post(`/api/migrations/svq/${m.id}/cutover`, { ...creds(), mark_source: mark })
        const bad = (r.data.zones || []).filter(z => !z.published)
        store.showNotification(bad.length ? `Corte hecho, pero ${bad.length} zona(s) no se publicaron: se reintentarán solas`
          : 'Corte hecho: DNS publicado', bad.length ? 'warning' : 'success')
        if (r.data.source && !r.data.source.ok) store.showNotification('Origen sin marcar: ' + r.data.source.error, 'warning')
        loadList()
      } catch (e) { store.showNotification(e.message, 'danger') }
    }
    const issueSsl = async (m) => {
      try {
        await api.post(`/api/migrations/svq/${m.id}/ssl`, {})
        store.showNotification("Emitiendo Let's Encrypt donde el DNS ya apunte aquí…", 'info')
        setTimeout(loadList, 15000)
      } catch (e) { store.showNotification(e.message, 'danger') }
    }

    loadList()
    onUnmounted(() => clearTimeout(timer))
    return { src, plan, analyzing, starting, job, migrations, canAnalyze, verifyOk, diffs,
      fmtBytes, phaseLabel, analyze, startImport, resync, mailCatchup, cutover, issueSsl }
  },
}
</script>

<style scoped>
.svqm { display: flex; flex-direction: column; gap: var(--sp-3); }
.svqm-beta { margin: 0; padding: var(--sp-2) var(--sp-3); border-radius: var(--r-md);
  background: var(--surface-2, var(--surface)); border: 1px dashed var(--border-strong); font-size: var(--fs-sm); }
.svqm-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--sp-3); }
.svqm-field { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-sm); }
.svqm-field--wide { grid-column: 1 / -1; }
.svq-input { height: 38px; padding: 0 var(--sp-3); width: 100%; background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-md); font-size: var(--fs-base); }
textarea.svq-input { height: auto; padding: var(--sp-2) var(--sp-3); }
.svqm-actions { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.svqm-h { margin: 0 0 var(--sp-2); font-size: var(--fs-base); }
.svqm-stats { display: flex; flex-wrap: wrap; gap: var(--sp-3); font-size: var(--fs-sm); margin-bottom: var(--sp-2); }
.svqm-err, .svqm-warn, .svqm-ok { display: flex; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md); font-size: var(--fs-sm); margin-bottom: var(--sp-2); }
.svqm-err { background: color-mix(in srgb, var(--color-danger, #dc2626) 10%, transparent); }
.svqm-warn { background: color-mix(in srgb, var(--color-warning, #d97706) 10%, transparent); }
.svqm-ok { background: color-mix(in srgb, var(--color-success, #16a34a) 10%, transparent); }
.svqm-err ul, .svqm-warn ul, .svqm-ok ul { margin: 4px 0 0; padding-left: 1.1rem; }
.svqm-progress { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-sm); }
.svqm-progress strong { margin-left: auto; }
.svqm-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.svqm-table th, .svqm-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
.svqm-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.svqm-phase { font-weight: 600; }
.svqm-phase.is-cutover { color: var(--color-success, #16a34a); }
.svqm-phase.is-failed { color: var(--color-danger, #dc2626); }
.svqm-small { font-size: var(--fs-xs, 12px); margin: 4px 0 0; }
.mono { font-family: var(--font-mono, monospace); }
.mig-mini-btn { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; font-size: var(--fs-sm);
  border: 1px solid var(--border-strong); border-radius: var(--r-md); background: var(--surface); color: var(--text); cursor: pointer; }
.mig-mini-btn:disabled { opacity: .5; cursor: not-allowed; }
.mig-mini-btn--danger { border-color: var(--color-danger, #dc2626); color: var(--color-danger, #dc2626); }
@media (max-width: 640px) { .svqm-table thead { display: none; } .svqm-table td { display: block; border: 0; padding: 2px 0; }
  .svqm-table tr { display: block; padding: 8px 0; border-bottom: 1px solid var(--border); } }
</style>
