<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2><i class="bi bi-folder2-open"></i> Archivos</h2>
      <div class="d-flex gap-2">
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

    <div class="row g-3 mb-3">
      <div class="col-md-5">
        <select v-model="selectedDomainId" class="form-select" @change="changeDomain">
          <option value="">Selecciona un dominio</option>
          <option v-for="domain in domains" :key="domain.id" :value="domain.id">
            {{ domain.domain_name }}
          </option>
        </select>
      </div>
      <div class="col-md-7">
        <div class="input-group">
          <button class="btn btn-outline-secondary" @click="goUp" :disabled="!currentPath">
            <i class="bi bi-arrow-up"></i>
          </button>
          <span class="form-control font-monospace bg-light">{{ breadcrumb }}</span>
          <button class="btn btn-outline-primary" @click="createFolder" :disabled="!selectedDomainId">
            <i class="bi bi-folder-plus"></i>
          </button>
        </div>
      </div>
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
                <th>Nombre</th>
                <th>Tamaño</th>
                <th>Modificado</th>
                <th>Permisos</th>
                <th class="text-end">Acciones</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in entries" :key="entry.path">
                <td>
                  <button
                    v-if="entry.type === 'directory'"
                    class="btn btn-link p-0 text-decoration-none fw-semibold"
                    @click="openDirectory(entry)"
                  >
                    <i class="bi bi-folder-fill text-warning me-2"></i>{{ entry.name }}
                  </button>
                  <span v-else>
                    <i class="bi bi-file-earmark text-secondary me-2"></i>{{ entry.name }}
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

    <Modal :isOpen="showEditor" :title="editingPath" @close="closeEditor">
      <div>
        <textarea v-model="editorContent" class="form-control font-monospace file-editor" spellcheck="false"></textarea>
        <div class="d-flex gap-2 mt-3">
          <button class="btn btn-primary" @click="saveFile" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            Guardar
          </button>
          <button class="btn btn-secondary" @click="closeEditor">Cancelar</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script>
import { computed, onMounted, ref } from 'vue'
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
    const uploadProgress = ref(null)   // null = idle, 0-100 = subiendo
    const uploadFileNames = ref('')    // nombres de los archivos en subida
    const extracting = ref(null)       // path del ZIP que se está extrayendo

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

      // Resumen de nombres para mostrar en la barra
      const names = Array.from(files).map(f => f.name)
      uploadFileNames.value = names.length <= 2
        ? names.join(', ')
        : `${names[0]} y ${names.length - 1} más`

      uploadProgress.value = 0
      try {
        await api.uploadDomainFiles(
          selectedDomainId.value,
          currentPath.value,
          files,
          (pct) => { uploadProgress.value = pct }
        )
        store.showNotification(
          `${files.length} archivo${files.length > 1 ? 's' : ''} subido${files.length > 1 ? 's' : ''} correctamente`,
          'success'
        )
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
        store.showNotification(
          `ZIP extraído correctamente (${result.files_extracted} elementos)`,
          'success'
        )
        await loadFiles()
      } catch (error) {
        store.showNotification(`Error extrayendo ZIP: ${error.message}`, 'danger')
      } finally {
        extracting.value = null
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
      let size = bytes
      let unit = 0
      while (size >= 1024 && unit < units.length - 1) {
        size /= 1024
        unit += 1
      }
      return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
    }

    const formatDate = (date) => date ? new Date(date).toLocaleString() : '-'

    const isEditable = (entry) => {
      const ext = entry.name.split('.').pop()?.toLowerCase()
      return editableExtensions.includes(ext)
    }

    const isZip = (entry) => entry.name.toLowerCase().endsWith('.zip')

    onMounted(loadDomains)

    return {
      domains, entries, selectedDomainId, currentPath, breadcrumb, loading, disabled,
      showEditor, editingPath, editorContent, saving,
      uploadProgress, uploadFileNames, extracting,
      loadFiles, changeDomain, openDirectory, goUp, createFolder, uploadFiles,
      editFile, saveFile, closeEditor, downloadFile, renameEntry, deleteEntry,
      extractZip, formatSize, formatDate, isEditable, isZip,
    }
  },
}
</script>

<style scoped>
.file-editor {
  min-height: 55vh;
  resize: vertical;
  white-space: pre;
  overflow-wrap: normal;
  overflow-x: auto;
}
</style>
