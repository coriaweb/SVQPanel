<template>
  <div class="sv-view">
    <div class="page-head-row" style="align-items:center">
      <h2 style="margin:0"><i class="bi bi-folder2-open"></i> Archivos</h2>
      <div class="d-flex align-items-center gap-2">
        <div class="form-check form-switch mb-0" title="Si está desactivado, los archivos con el mismo nombre no se sobreescriben">
          <input class="form-check-input" type="checkbox" id="overwriteCheck" v-model="uploadOverwrite">
          <label class="form-check-label small text-muted" for="overwriteCheck">Sobreescribir</label>
        </div>
        <button class="btn btn-outline-secondary" @click="loadFiles" :disabled="!selectedDomainId || loading">
          <i class="bi bi-arrow-clockwise"></i>
        </button>
        <label class="btn btn-primary mb-0" :class="{ disabled: !selectedDomainId || uploadProgress !== null }">
          <span v-if="uploadProgress !== null" class="spinner-border spinner-border-sm me-1" role="status"></span>
          <i v-else class="bi bi-upload"></i>
          {{ uploadProgress !== null ? 'Subiendo…' : 'Subir' }}
          <input type="file" multiple class="d-none" @change="uploadFiles" :disabled="!selectedDomainId || uploadProgress !== null" />
        </label>
      </div>
    </div>

    <div v-if="disabled" class="alert alert-warning">
      <i class="bi bi-exclamation-triangle-fill me-2"></i>
      El administrador de archivos no está habilitado en este servidor.
    </div>

    <!-- Barra de progreso de subida -->
    <div v-if="uploadProgress !== null" class="card border-primary mb-3">
      <div class="card-body py-2 px-3">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <small class="fw-semibold text-primary">
            <i class="bi bi-cloud-upload me-1"></i>
            <span v-if="uploadProgress < 100">Subiendo archivos… {{ uploadProgress }}%</span>
            <span v-else>Procesando en el servidor…</span>
          </small>
          <small class="text-muted">{{ uploadFileNames }}</small>
        </div>
        <div class="progress" style="height: 8px;">
          <div
            class="progress-bar progress-bar-striped"
            :class="uploadProgress < 100 ? 'progress-bar-animated' : 'bg-success'"
            role="progressbar"
            :style="{ width: uploadProgress + '%' }"
            :aria-valuenow="uploadProgress"
            aria-valuemin="0"
            aria-valuemax="100"
          ></div>
        </div>
      </div>
    </div>

    <div class="fm-toolbar">
      <select v-model="selectedDomainId" class="form-select" @change="changeDomain" style="max-width:220px">
        <option value="">Selecciona un dominio</option>
        <option v-for="domain in domains" :key="domain.id" :value="domain.id">{{ domain.domain_name }}</option>
      </select>
      <div class="input-group" style="flex:1">
        <button class="btn btn-outline-secondary" @click="goUp" :disabled="!currentPath">
          <i class="bi bi-arrow-up"></i>
        </button>
        <span class="form-control font-monospace" style="background:var(--surface-inset)">{{ breadcrumb }}</span>
        <button class="btn btn-outline-primary" @click="createFolder" :disabled="!selectedDomainId">
          <i class="bi bi-folder-plus"></i>
        </button>
      </div>
    </div>

    <!-- Barra de acciones en lote -->
    <div v-if="selected.size > 0" class="bulk-bar">
      <span class="bulk-count">
        <i class="bi bi-check2-square me-1"></i>
        {{ selected.size }} seleccionado{{ selected.size !== 1 ? 's' : '' }}
      </span>
      <button class="btn btn-sm btn-outline-danger" @click="deleteSelected" :disabled="bulkDeleting">
        <span v-if="bulkDeleting" class="spinner-border spinner-border-sm me-1"></span>
        <i v-else class="bi bi-trash me-1"></i>
        Eliminar seleccionados
      </button>
      <button class="btn btn-sm btn-outline-secondary" @click="clearSelection">
        Cancelar
      </button>
    </div>

    <div class="card">
      <div class="card-body p-0">
        <div v-if="loading" class="text-center py-5">
          <div class="spinner-border" role="status"></div>
        </div>
        <div v-else-if="!selectedDomainId" class="alert alert-info m-3 mb-0">
          Selecciona un dominio para ver sus archivos.
        </div>
        <div v-else-if="entries.length === 0" class="alert alert-info m-3 mb-0">
          Esta carpeta está vacía.
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th style="width:36px">
                  <input
                    type="checkbox"
                    class="form-check-input"
                    :checked="allSelected"
                    :indeterminate.prop="someSelected"
                    @change="toggleAll"
                    title="Seleccionar todo"
                  >
                </th>
                <th>Nombre</th>
                <th>Tamaño</th>
                <th>Modificado</th>
                <th>Permisos</th>
                <th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in entries" :key="entry.path" :class="{ 'table-active': selected.has(entry.path) }">
                <td>
                  <input
                    type="checkbox"
                    class="form-check-input"
                    :checked="selected.has(entry.path)"
                    @change="toggleSelect(entry)"
                  >
                </td>
                <td>
                  <button
                    v-if="entry.type === 'directory'"
                    class="btn btn-link p-0 text-decoration-none fw-semibold"
                    @click="openDirectory(entry)"
                  >
                    <i class="bi bi-folder-fill text-warning me-2"></i>{{ entry.name }}
                  </button>
                  <span v-else>
                    <i :class="fileIcon(entry)" class="me-2"></i>{{ entry.name }}
                  </span>
                </td>
                <td>{{ entry.type === 'directory' ? '-' : formatSize(entry.size) }}</td>
                <td>{{ formatDate(entry.modified_at) }}</td>
                <td><code>{{ entry.permissions }}</code></td>
                <td class="text-end">
                  <div class="btn-group btn-group-sm">
                    <button
                      v-if="entry.type === 'file' && isEditable(entry)"
                      class="btn btn-outline-primary"
                      title="Editar"
                      @click="editFile(entry)"
                    >
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button
                      v-if="entry.type === 'file'"
                      class="btn btn-outline-success"
                      title="Descargar"
                      @click="downloadFile(entry)"
                    >
                      <i class="bi bi-download"></i>
                    </button>
                    <button
                      v-if="entry.type === 'file' && isZip(entry)"
                      class="btn btn-outline-warning"
                      title="Extraer ZIP aquí"
                      :disabled="extracting === entry.path"
                      @click="extractZip(entry)"
                    >
                      <span v-if="extracting === entry.path" class="spinner-border spinner-border-sm"></span>
                      <i v-else class="bi bi-file-zip"></i>
                    </button>
                    <button class="btn btn-outline-secondary" title="Renombrar" @click="renameEntry(entry)">
                      <i class="bi bi-input-cursor-text"></i>
                    </button>
                    <button class="btn btn-outline-secondary" title="Permisos" @click="openChmod(entry)">
                      <i class="bi bi-lock"></i>
                    </button>
                    <button class="btn btn-outline-danger" title="Eliminar" @click="deleteEntry(entry)">
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

    <Modal :isOpen="showEditor" :title="editingPath" size="lg" @close="closeEditor">
      <div>
        <div class="d-flex justify-content-between align-items-center mb-2">
          <div class="d-flex gap-2 align-items-center">
            <span class="badge bg-secondary font-monospace">{{ editingLang }}</span>
            <small class="text-muted">Ctrl+S para guardar · Tab inserta espacios</small>
          </div>
          <div class="form-check form-switch mb-0">
            <input class="form-check-input" type="checkbox" id="wrapCheck" v-model="editorWrap">
            <label class="form-check-label small text-muted" for="wrapCheck">Ajuste de línea</label>
          </div>
        </div>

        <textarea
          v-model="editorContent"
          class="form-control font-monospace file-editor"
          :class="{ 'file-editor-nowrap': !editorWrap }"
          spellcheck="false"
          @keydown="handleEditorKeydown"
        ></textarea>

        <div class="d-flex justify-content-between align-items-center mt-1 px-1">
          <small class="text-muted">
            {{ editorStats.lines }} líneas · {{ editorStats.chars }} caracteres · {{ editorStats.sizeLabel }}
          </small>
          <small class="text-muted">UTF-8</small>
        </div>

        <div class="d-flex gap-2 mt-3">
          <button class="btn btn-primary" @click="saveFile" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            <i v-else class="bi bi-floppy me-1"></i>
            Guardar
          </button>
          <button class="btn btn-secondary" @click="closeEditor">Cancelar</button>
        </div>
      </div>
    </Modal>

    <!-- Modal de permisos (chmod) -->
    <Modal :isOpen="showChmod" :title="`Permisos: ${chmodEntry?.name ?? ''}`" size="sm" @close="showChmod = false">
      <div>
        <table class="table table-sm table-bordered text-center align-middle mb-3">
          <thead class="table-light">
            <tr>
              <th class="text-start"></th>
              <th>Leer</th>
              <th>Escribir</th>
              <th>Ejecutar</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(label, key) in { owner: 'Propietario', group: 'Grupo', other: 'Otros' }" :key="key">
              <td class="text-start fw-semibold ps-2">{{ label }}</td>
              <td><input type="checkbox" v-model="chmodBits[key].r" class="form-check-input"></td>
              <td><input type="checkbox" v-model="chmodBits[key].w" class="form-check-input"></td>
              <td><input type="checkbox" v-model="chmodBits[key].x" class="form-check-input"></td>
            </tr>
          </tbody>
        </table>
        <div class="d-flex align-items-center gap-3 mb-3">
          <span class="text-muted small">Valor octal:</span>
          <code class="fs-4 fw-bold text-primary">{{ chmodOctal }}</code>
          <span class="text-muted small ms-auto">
            <span v-if="chmodEntry?.type === 'directory'">
              Típico: <code>755</code> (directorios)
            </span>
            <span v-else>
              Típico: <code>644</code> (archivos)
            </span>
          </span>
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-primary" @click="applyChmod" :disabled="savingChmod">
            <span v-if="savingChmod" class="spinner-border spinner-border-sm me-1"></span>
            Aplicar
          </button>
          <button class="btn btn-secondary" @click="showChmod = false">Cancelar</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import Modal from '../components/Modal.vue'
import { useMainStore } from '../stores/useMainStore'

const editableExtensions = ['txt', 'css', 'js', 'ts', 'html', 'htm', 'php', 'json', 'md', 'xml', 'yml', 'yaml', 'env', 'ini', 'conf', 'log']

export default {
  name: 'FileManager',
  components: { Modal },
  setup() {
    const store = useMainStore()
    const route = useRoute()
    const domains = ref([])
    const entries = ref([])
    const selectedDomainId = ref('')
    const currentPath = ref('')
    const loading = ref(false)
    const disabled = ref(false)
    const showEditor = ref(false)
    const editingPath = ref('')
    const editorContent = ref('')
    const saving = ref(false)
    const uploadProgress = ref(null)
    const uploadFileNames = ref('')
    const uploadOverwrite = ref(true)
    const extracting = ref(null)

    // — Selección múltiple —
    const selected = ref(new Set())
    const bulkDeleting = ref(false)

    const allSelected = computed(() =>
      entries.value.length > 0 && entries.value.every(e => selected.value.has(e.path))
    )
    const someSelected = computed(() =>
      selected.value.size > 0 && !allSelected.value
    )

    const toggleSelect = (entry) => {
      const s = new Set(selected.value)
      if (s.has(entry.path)) s.delete(entry.path)
      else s.add(entry.path)
      selected.value = s
    }

    const toggleAll = () => {
      if (allSelected.value) {
        selected.value = new Set()
      } else {
        selected.value = new Set(entries.value.map(e => e.path))
      }
    }

    const clearSelection = () => { selected.value = new Set() }

    const deleteSelected = async () => {
      const paths = [...selected.value]
      const names = entries.value
        .filter(e => selected.value.has(e.path))
        .map(e => e.name)
      if (!confirm(`¿Eliminar ${paths.length} elemento${paths.length !== 1 ? 's' : ''}?\n\n${names.join('\n')}`)) return
      bulkDeleting.value = true
      let errors = 0
      for (const path of paths) {
        try {
          await api.deleteDomainEntry(selectedDomainId.value, path)
        } catch {
          errors++
        }
      }
      bulkDeleting.value = false
      selected.value = new Set()
      if (errors === 0) {
        store.showNotification(`${paths.length} elemento${paths.length !== 1 ? 's' : ''} eliminado${paths.length !== 1 ? 's' : ''}`, 'success')
      } else {
        store.showNotification(`Eliminados con ${errors} error${errors !== 1 ? 'es' : ''}`, 'warning')
      }
      await loadFiles()
    }

    // — Editor —
    const editorWrap = ref(false)
    const editingLang = computed(() => {
      const ext = editingPath.value.split('.').pop()?.toLowerCase() || ''
      const map = {
        php: 'PHP', js: 'JavaScript', ts: 'TypeScript', html: 'HTML', htm: 'HTML',
        css: 'CSS', json: 'JSON', xml: 'XML', yml: 'YAML', yaml: 'YAML',
        md: 'Markdown', sql: 'SQL', vue: 'Vue', env: 'ENV', sh: 'Shell',
        ini: 'INI', conf: 'Conf', txt: 'Texto', log: 'Log',
      }
      return map[ext] || ext.toUpperCase() || 'Texto'
    })
    const editorStats = computed(() => {
      const text = editorContent.value
      const lines = text ? text.split('\n').length : 0
      const chars = text.length
      const bytes = new Blob([text]).size
      const units = ['B', 'KB', 'MB']
      let s = bytes; let u = 0
      while (s >= 1024 && u < units.length - 1) { s /= 1024; u++ }
      return { lines, chars, sizeLabel: `${s.toFixed(u === 0 ? 0 : 1)} ${units[u]}` }
    })

    // — Chmod —
    const showChmod = ref(false)
    const savingChmod = ref(false)
    const chmodEntry = ref(null)
    const chmodBits = ref({
      owner: { r: false, w: false, x: false },
      group: { r: false, w: false, x: false },
      other: { r: false, w: false, x: false },
    })
    const chmodOctal = computed(() => {
      const toInt = (b) => (b.r ? 4 : 0) + (b.w ? 2 : 0) + (b.x ? 1 : 0)
      return `${toInt(chmodBits.value.owner)}${toInt(chmodBits.value.group)}${toInt(chmodBits.value.other)}`
    })

    const breadcrumb = computed(() => '/' + (currentPath.value || ''))

    const loadDomains = async () => {
      try {
        domains.value = await api.getFileManagerDomains()
        const requestedDomain = route.query.domain ? String(route.query.domain) : ''
        const requestedExists = domains.value.some(domain => String(domain.id) === requestedDomain)
        if (!selectedDomainId.value && domains.value.length) {
          selectedDomainId.value = requestedExists ? requestedDomain : String(domains.value[0].id)
          await loadFiles()
        }
      } catch (error) {
        if ((error.message || '').toLowerCase().includes('no está habilitado')) disabled.value = true
        else store.showNotification(`Error cargando dominios: ${error.message}`, 'danger')
      }
    }

    const loadFiles = async () => {
      if (!selectedDomainId.value) return
      loading.value = true
      selected.value = new Set()
      try {
        entries.value = await api.listDomainFiles(selectedDomainId.value, currentPath.value)
      } catch (error) {
        store.showNotification(`Error cargando archivos: ${error.message}`, 'danger')
      } finally {
        loading.value = false
      }
    }

    const changeDomain = async () => {
      currentPath.value = ''
      await loadFiles()
    }

    const openDirectory = async (entry) => {
      currentPath.value = entry.path
      await loadFiles()
    }

    const goUp = async () => {
      const parts = currentPath.value.split('/').filter(Boolean)
      parts.pop()
      currentPath.value = parts.join('/')
      await loadFiles()
    }

    const createFolder = async () => {
      const name = prompt('Nombre de la carpeta')
      if (!name) return
      try {
        await api.createDomainDirectory(selectedDomainId.value, currentPath.value, name)
        store.showNotification('Carpeta creada', 'success')
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error creando carpeta: ${error.message}`, 'danger')
      }
    }

    const uploadFiles = async (event) => {
      const files = event.target.files
      if (!files?.length) return
      const names = Array.from(files).map(f => f.name)
      uploadFileNames.value = names.length <= 2 ? names.join(', ') : `${names[0]} y ${names.length - 1} más`
      uploadProgress.value = 0
      try {
        const result = await api.uploadDomainFiles(
          selectedDomainId.value, currentPath.value, files,
          (pct) => { uploadProgress.value = pct },
          uploadOverwrite.value
        )
        const skipped = result?.skipped?.length ?? 0
        const saved   = result?.files?.length   ?? files.length
        const msg = skipped
          ? `${saved} subido${saved !== 1 ? 's' : ''}, ${skipped} omitido${skipped !== 1 ? 's' : ''} (ya existía${skipped !== 1 ? 'n' : ''})`
          : `${saved} archivo${saved !== 1 ? 's' : ''} subido${saved !== 1 ? 's' : ''} correctamente`
        store.showNotification(msg, skipped ? 'warning' : 'success')
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error subiendo archivos: ${error.message}`, 'danger')
      } finally {
        uploadProgress.value = null
        uploadFileNames.value = ''
        event.target.value = ''
      }
    }

    const extractZip = async (entry) => {
      if (!confirm(`¿Extraer "${entry.name}" en esta carpeta?`)) return
      extracting.value = entry.path
      try {
        const result = await api.extractDomainZip(selectedDomainId.value, entry.path)
        store.showNotification(`ZIP extraído correctamente (${result.files_extracted} elementos)`, 'success')
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error extrayendo ZIP: ${error.message}`, 'danger')
      } finally {
        extracting.value = null
      }
    }

    const handleEditorKeydown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault()
        if (!saving.value) saveFile()
        return
      }
      if (event.key === 'Tab') {
        event.preventDefault()
        const ta = event.target
        const start = ta.selectionStart
        const end   = ta.selectionEnd
        const indent = '  '
        editorContent.value =
          editorContent.value.substring(0, start) + indent + editorContent.value.substring(end)
        nextTick(() => { ta.selectionStart = ta.selectionEnd = start + indent.length })
      }
    }

    const openChmod = (entry) => {
      chmodEntry.value = entry
      const digits = (entry.permissions || '644').padStart(3, '0').slice(-3)
      const parse  = (d) => ({ r: !!(parseInt(d) & 4), w: !!(parseInt(d) & 2), x: !!(parseInt(d) & 1) })
      chmodBits.value = { owner: parse(digits[0]), group: parse(digits[1]), other: parse(digits[2]) }
      showChmod.value = true
    }

    const applyChmod = async () => {
      savingChmod.value = true
      try {
        await api.chmodDomainEntry(selectedDomainId.value, chmodEntry.value.path, chmodOctal.value)
        store.showNotification(`Permisos cambiados a ${chmodOctal.value}`, 'success')
        showChmod.value = false
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error cambiando permisos: ${error.message}`, 'danger')
      } finally {
        savingChmod.value = false
      }
    }

    const editFile = async (entry) => {
      try {
        const data = await api.readDomainFile(selectedDomainId.value, entry.path)
        editingPath.value = entry.path
        editorContent.value = data.content
        showEditor.value = true
      } catch (error) {
        store.showNotification(`No se puede editar: ${error.message}`, 'warning')
      }
    }

    const saveFile = async () => {
      saving.value = true
      try {
        await api.writeDomainFile(selectedDomainId.value, editingPath.value, editorContent.value)
        store.showNotification('Archivo guardado', 'success')
        closeEditor()
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error guardando: ${error.message}`, 'danger')
      } finally {
        saving.value = false
      }
    }

    const closeEditor = () => {
      showEditor.value = false
      editingPath.value = ''
      editorContent.value = ''
    }

    const downloadFile = async (entry) => {
      try {
        const blob = await api.downloadDomainFile(selectedDomainId.value, entry.path)
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = entry.name
        a.click()
        URL.revokeObjectURL(url)
      } catch (error) {
        store.showNotification(`Error descargando: ${error.message}`, 'danger')
      }
    }

    const renameEntry = async (entry) => {
      const newName = prompt('Nuevo nombre', entry.name)
      if (!newName || newName === entry.name) return
      try {
        await api.renameDomainEntry(selectedDomainId.value, entry.path, newName)
        store.showNotification('Elemento renombrado', 'success')
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error renombrando: ${error.message}`, 'danger')
      }
    }

    const deleteEntry = async (entry) => {
      if (!confirm(`¿Eliminar "${entry.name}"?`)) return
      try {
        await api.deleteDomainEntry(selectedDomainId.value, entry.path)
        store.showNotification('Elemento eliminado', 'success')
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error eliminando: ${error.message}`, 'danger')
      }
    }

    const formatSize = (bytes) => {
      if (!bytes) return '0 B'
      const units = ['B', 'KB', 'MB', 'GB']
      let size = bytes; let unit = 0
      while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++ }
      return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
    }

    const formatDate = (date) => date ? new Date(date).toLocaleString() : '-'
    const isEditable = (entry) => editableExtensions.includes(entry.name.split('.').pop()?.toLowerCase())
    const isZip = (entry) => entry.name.toLowerCase().endsWith('.zip')

    const fileIcon = (entry) => {
      const ext = entry.name.split('.').pop()?.toLowerCase()
      if (['zip', 'gz', 'tar', 'rar', '7z', 'bz2', 'xz'].includes(ext)) return 'bi bi-file-zip-fill text-warning'
      if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'ico', 'bmp'].includes(ext)) return 'bi bi-file-image text-info'
      if (['mp4', 'avi', 'mov', 'mkv', 'webm'].includes(ext)) return 'bi bi-file-play text-danger'
      if (['mp3', 'ogg', 'wav', 'flac', 'aac'].includes(ext)) return 'bi bi-file-music text-danger'
      if (['pdf'].includes(ext)) return 'bi bi-file-pdf text-danger'
      if (['php'].includes(ext)) return 'bi bi-file-code text-primary'
      if (['html', 'htm', 'css', 'js', 'ts', 'vue', 'json', 'xml', 'yml', 'yaml'].includes(ext)) return 'bi bi-file-code text-success'
      if (['txt', 'md', 'log', 'csv'].includes(ext)) return 'bi bi-file-text text-secondary'
      if (['sql'].includes(ext)) return 'bi bi-file-earmark-data text-warning'
      return 'bi bi-file-earmark text-secondary'
    }

    onMounted(loadDomains)

    return {
      domains, entries, selectedDomainId, currentPath, breadcrumb, loading, disabled,
      loadFiles, changeDomain, openDirectory, goUp, createFolder,
      uploadProgress, uploadFileNames, uploadOverwrite, uploadFiles,
      showEditor, editingPath, editorContent, saving,
      editorWrap, editingLang, editorStats,
      handleEditorKeydown, editFile, saveFile, closeEditor,
      downloadFile, renameEntry, deleteEntry,
      extracting, extractZip,
      showChmod, savingChmod, chmodEntry, chmodBits, chmodOctal, openChmod, applyChmod,
      selected, bulkDeleting, allSelected, someSelected,
      toggleSelect, toggleAll, clearSelection, deleteSelected,
      formatSize, formatDate, isEditable, isZip, fileIcon,
    }
  },
}
</script>

<style scoped>
.sv-view { display: flex; flex-direction: column; gap: 16px; }
.fm-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.file-editor {
  min-height: 60vh;
  resize: vertical;
  font-size: 0.875rem;
  line-height: 1.5;
  tab-size: 2;
  white-space: pre-wrap;
  overflow-wrap: break-word;
}
.file-editor.file-editor-nowrap {
  white-space: pre;
  overflow-wrap: normal;
  overflow-x: auto;
}

.bulk-bar {
  display: flex;
  align-items: center;
  gap: .75rem;
  padding: .6rem 1rem;
  margin-bottom: .75rem;
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-2));
  border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  border-radius: var(--radius-md);
}
.bulk-count {
  font-size: .875rem;
  font-weight: 500;
  color: var(--accent);
  margin-right: auto;
}
</style>
