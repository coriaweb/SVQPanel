<template>
  <BaseCard title="Composer" icon="box-seam">
    <template #actions>
      <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="loading" @click="loadAll">Refrescar</BaseButton>
    </template>

    <p class="cm-intro dd-muted">
      Gestiona las dependencias PHP de tu proyecto (PhpMailer, Guzzle, etc.). Los
      comandos se ejecutan en el directorio de tu web como tu usuario, igual que
      en la terminal. <b>No</b> actualiza el propio Composer, solo tus paquetes.
    </p>

    <div v-if="loading && !status" class="cm-loading"><span class="spinner"></span> Analizando…</div>
    <div v-else-if="errorMsg" class="cm-error"><i class="bi bi-exclamation-triangle"></i> {{ errorMsg }}</div>

    <template v-else-if="status">
      <!-- Resumen -->
      <div class="cm-summary">
        <div class="cm-stat"><span class="cm-stat__k">Composer</span><span class="cm-stat__v mono">{{ status.composer_version || '—' }}</span></div>
        <div class="cm-stat"><span class="cm-stat__k">composer.json</span><span class="cm-stat__v">{{ status.has_json ? 'Sí' : 'No' }}</span></div>
        <div class="cm-stat"><span class="cm-stat__k">vendor/</span><span class="cm-stat__v">{{ status.has_vendor ? 'Instalado' : 'No' }}</span></div>
        <div class="cm-stat"><span class="cm-stat__k">Dependencias</span><span class="cm-stat__v">{{ status.declared_count }}</span></div>
      </div>

      <!-- Instalar un paquete -->
      <div class="cm-add">
        <label class="app-field cm-add__field">
          <span>Instalar un paquete</span>
          <div class="cm-add__row">
            <input class="svq-input mono" v-model.trim="newPkg" placeholder="vendor/paquete  (ej. phpmailer/phpmailer)"
                   :disabled="!!busy" @keyup.enter="doRequire" />
            <label class="cm-dev"><input type="checkbox" v-model="newDev" :disabled="!!busy" /> --dev</label>
            <BaseButton variant="primary" size="sm" icon="plus-lg" :loading="busy==='require'"
                        :disabled="!newPkg" @click="doRequire">Instalar</BaseButton>
          </div>
        </label>
        <small class="dd-muted">
          Formato <code>vendor/nombre</code>. Puedes fijar versión con <code>:^6.9</code>.
          <code>--dev</code> = solo para desarrollo (no en producción).
        </small>
      </div>

      <!-- Acciones globales -->
      <div class="cm-actions">
        <BaseButton variant="ghost" size="sm" icon="download" :loading="busy==='install'"
                    :disabled="!status.has_json" @click="doInstall" title="Instala lo declarado en composer.json">
          composer install
        </BaseButton>
        <BaseButton variant="ghost" size="sm" icon="arrow-up-circle" :loading="busy==='update'"
                    :disabled="!status.has_json" @click="confirmUpdateAll" title="Actualiza TODAS tus dependencias">
          Actualizar todo
        </BaseButton>
      </div>

      <!-- Paquetes instalados -->
      <div class="cm-pkgs">
        <div class="cm-pkgs__head">
          <span class="cm-pkgs__title">Paquetes instalados</span>
          <span class="dd-muted">{{ packages.length }}</span>
        </div>
        <div v-if="loadingPkgs" class="cm-loading"><span class="spinner"></span> Cargando…</div>
        <table v-else-if="packages.length" class="cm-table">
          <thead><tr><th>Paquete</th><th>Versión</th><th></th></tr></thead>
          <tbody>
            <tr v-for="p in packages" :key="p.name">
              <td>
                <span class="cm-name mono">{{ p.name }}</span>
                <span v-if="p.description" class="cm-desc dd-muted">{{ p.description }}</span>
              </td>
              <td class="mono">{{ p.version }}</td>
              <td class="cm-rowactions">
                <button class="cm-mini" :disabled="!!busy" @click="doUpdateOne(p.name)" title="Actualizar este paquete"><i class="bi bi-arrow-up-circle"></i></button>
                <button class="cm-mini cm-mini--danger" :disabled="!!busy" @click="doRemove(p.name)" title="Quitar"><i class="bi bi-trash"></i></button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="dd-muted cm-empty">
          Todavía no hay paquetes instalados. Usa «Instalar un paquete» para añadir el primero.
        </p>
      </div>

      <!-- Salida del último comando -->
      <div v-if="lastOutput" class="cm-output">
        <div class="cm-output__head">
          <span><i class="bi bi-terminal"></i> Salida del último comando</span>
          <button class="cm-output__clear" @click="lastOutput = ''" title="Ocultar"><i class="bi bi-x-lg"></i></button>
        </div>
        <pre class="cm-output__body mono">{{ lastOutput }}</pre>
      </div>
    </template>
  </BaseCard>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'

export default {
  name: 'ComposerManager',
  components: { BaseCard, BaseButton },
  props: {
    domainId:   { type: [Number, String], default: null },
    domainName: { type: String, default: '' },
  },
  setup(props) {
    const store = useMainStore()
    const route = useRoute()
    const did = computed(() => {
      let n = parseInt(props.domainId, 10)
      if (!Number.isInteger(n)) n = parseInt(route.params.id, 10)
      return Number.isInteger(n) ? n : null
    })

    const status = ref(null)
    const packages = ref([])
    const loading = ref(true)
    const loadingPkgs = ref(false)
    const errorMsg = ref('')
    const busy = ref('')            // acción en curso: desactiva botones
    const lastOutput = ref('')
    const newPkg = ref('')
    const newDev = ref(false)

    const loadStatus = async () => {
      if (did.value == null) { loading.value = false; return }
      try {
        const r = await api.getComposerStatus(did.value)
        status.value = r.data
      } catch (e) { errorMsg.value = e.message || 'No pude leer el estado de Composer' }
    }

    const loadPackages = async () => {
      if (did.value == null) return
      loadingPkgs.value = true
      try { const r = await api.getComposerPackages(did.value); packages.value = r.data || [] }
      catch (e) { /* silencioso: sin vendor/ no hay paquetes */ }
      finally { loadingPkgs.value = false }
    }

    const loadAll = async () => {
      loading.value = true; errorMsg.value = ''
      await loadStatus()
      await loadPackages()
      loading.value = false
    }

    // Ejecuta una acción y refresca estado + paquetes con la salida en pantalla.
    const run = async (action, payload, busyId) => {
      if (did.value == null) return
      busy.value = busyId || action
      try {
        const r = await api.composerAction(did.value, action, payload)
        lastOutput.value = r.data?.output || 'Hecho.'
        store.showNotification('Composer: ' + action + ' completado', 'success')
        await loadStatus()
        await loadPackages()
      } catch (e) {
        lastOutput.value = e.message || 'Error'
        store.showNotification('Error: ' + (e.message || 'falló el comando'), 'danger')
      } finally { busy.value = '' }
    }

    const doRequire = async () => {
      if (!newPkg.value) return
      const ok = await run('require', { package: newPkg.value, dev: newDev.value }, 'require')
      newPkg.value = ''; newDev.value = false
      return ok
    }
    const doRemove = (name) => {
      if (!confirm(`¿Quitar el paquete "${name}"? Se eliminará de tu vendor/.`)) return
      run('remove', { package: name }, 'r:' + name)
    }
    const doUpdateOne = (name) => run('update', { package: name }, 'u:' + name)
    const doInstall = () => run('install', {}, 'install')
    const confirmUpdateAll = () => {
      if (!confirm('«Actualizar todo» sube TODAS tus dependencias a versiones nuevas compatibles. Puede cambiar el comportamiento de tu web. ¿Continuar?')) return
      run('update', {}, 'update')
    }

    onMounted(loadAll)
    watch(did, (v, prev) => { if (v != null && prev == null) loadAll() })

    return {
      status, packages, loading, loadingPkgs, errorMsg, busy, lastOutput,
      newPkg, newDev, loadAll,
      doRequire, doRemove, doUpdateOne, doInstall, confirmUpdateAll,
    }
  },
}
</script>

<style scoped>
.cm-intro { font-size:.88rem; margin:0 0 1rem; line-height:1.5; }
.cm-loading, .cm-error { display:flex; align-items:center; gap:.5rem; padding:.75rem 0; color: var(--text-muted); }
.cm-error { color: var(--danger); }
.cm-summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap:.5rem; margin-bottom:1rem; }
.cm-stat { background: var(--surface-inset); border:1px solid var(--border); border-radius: var(--radius-md); padding:.5rem .75rem; }
.cm-stat__k { display:block; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color: var(--text-muted); }
.cm-stat__v { font-weight:600; }
.cm-add { padding:.85rem 0; border-top:1px solid var(--border); }
.cm-add__field span { display:block; font-weight:600; margin-bottom:.4rem; font-size:.88rem; }
.cm-add__row { display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; }
.cm-add__row .svq-input { flex:1; min-width:220px; }
.cm-dev { display:inline-flex; align-items:center; gap:.3rem; font-size:.82rem; color: var(--text-muted); white-space:nowrap; }
.cm-add small { display:block; margin-top:.4rem; line-height:1.4; }
.cm-add code, .cm-empty code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.8rem; }
.cm-actions { display:flex; gap:.5rem; flex-wrap:wrap; padding:.5rem 0 1rem; }
.cm-pkgs__head { display:flex; align-items:center; justify-content:space-between; gap:.75rem; margin:.5rem 0; }
.cm-pkgs__title { font-weight:600; }
.cm-table { width:100%; border-collapse: collapse; font-size:.86rem; }
.cm-table th { text-align:left; font-size:.72rem; text-transform:uppercase; color: var(--text-muted); padding:.4rem .5rem; border-bottom:1px solid var(--border); }
.cm-table td { padding:.5rem; border-bottom:1px solid var(--border); vertical-align:top; }
.cm-name { font-weight:600; display:block; }
.cm-desc { display:block; font-size:.78rem; margin-top:.15rem; }
.cm-rowactions { white-space:nowrap; text-align:right; }
.cm-mini { background:none; border:1px solid var(--border); border-radius: var(--radius-sm); width:30px; height:30px; cursor:pointer; color: var(--text); margin-left:.25rem; }
.cm-mini:hover:not(:disabled) { background: var(--surface-inset); }
.cm-mini:disabled { opacity:.5; cursor:not-allowed; }
.cm-mini--danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }
.cm-mini--danger:hover:not(:disabled) { background: color-mix(in srgb, var(--danger) 12%, transparent); }
.cm-empty { padding:1rem 0; }
.cm-output { margin-top:1rem; border:1px solid var(--border); border-radius: var(--radius-md); overflow:hidden; }
.cm-output__head { display:flex; align-items:center; justify-content:space-between; padding:.45rem .75rem; background: var(--surface-inset); font-size:.82rem; }
.cm-output__clear { background:none; border:none; color: var(--text-muted); cursor:pointer; }
.cm-output__body { margin:0; padding:.75rem; max-height:320px; overflow:auto; font-size:.8rem; white-space:pre-wrap; word-break:break-word; background: var(--surface); }
.mono { font-family: var(--font-mono, monospace); }
</style>
