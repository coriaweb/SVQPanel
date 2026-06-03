<template>
  <div>
    <div v-if="!showForm" class="ssl-info">
      <div v-if="ssl" class="alert alert-success">
        <i class="bi bi-shield-check"></i>
        <strong>Certificado Activo</strong>
        <div class="mt-2 small">
          <p>
            <strong>Dominio:</strong> {{ domain.domain_name }}<br>
            <strong>Emisor:</strong> {{ ssl.cert_info?.issuer || "Let's Encrypt" }}<br>
            <strong>Válido hasta:</strong> {{ formatDate(ssl.ssl_expires || ssl.cert_info?.not_after) }}<br>
            <strong>Auto-renovación:</strong> Habilitada (certbot.timer)
          </p>
        </div>
        <div class="mt-3 d-flex gap-2">
          <button class="btn btn-warning btn-sm" @click="renewSSL" :disabled="loading">
            <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
            Renovar
          </button>
          <button class="btn btn-danger btn-sm" @click="showRevokeConfirm = true" :disabled="loading">
            Revocar
          </button>
        </div>
      </div>
      <div v-else class="alert alert-info">
        <i class="bi bi-shield-x"></i>
        <strong>Sin Certificado SSL</strong>
        <p class="mt-2 mb-0">Este dominio no tiene un certificado SSL configurado.</p>
        <button class="btn btn-success btn-sm mt-3" @click="showForm = true" :disabled="loading">
          <i class="bi bi-plus-circle"></i> Crear Certificado
        </button>
      </div>

      <div v-if="showRevokeConfirm" class="alert alert-warning mt-3">
        <p class="mb-2">¿Está seguro de que desea revocar el certificado SSL?</p>
        <div class="d-flex gap-2">
          <button class="btn btn-danger btn-sm" @click="revokeSSL" :disabled="loading">
            Confirmar Revocación
          </button>
          <button class="btn btn-secondary btn-sm" @click="showRevokeConfirm = false" :disabled="loading">
            Cancelar
          </button>
        </div>
      </div>
    </div>

    <div v-else class="ssl-form">
      <p class="text-muted">Se creará un certificado Let's Encrypt para: <strong>{{ domain.domain_name }}</strong></p>
      <div class="alert alert-info">
        <small>
          <i class="bi bi-info-circle"></i>
          El proceso puede tomar algunos minutos. El dominio debe ser accesible desde Internet.
        </small>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-success" @click="createSSL" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
          Crear Certificado
        </button>
        <button class="btn btn-secondary" @click="showForm = false" :disabled="loading">
          Cancelar
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'SSLManager',
  props: {
    domain: {
      type: Object,
      required: true
    }
  },
  emits: ['reload'],
  setup(props, { emit }) {
    const store = useMainStore()
    const loading = ref(false)
    const showForm = ref(false)
    const showRevokeConfirm = ref(false)
    const ssl = ref(null)

    const loadSSL = async () => {
      try {
        const data = await api.getSSL(props.domain.id)
        // Solo considerar SSL activo si ssl_enabled o hay cert_info real
        ssl.value = (data?.ssl_enabled || data?.cert_info) ? data : null
      } catch (error) {
        ssl.value = null
      }
    }

    const createSSL = async () => {
      loading.value = true
      try {
        await api.createSSL(props.domain.id, {
          domain_name: props.domain.domain_name,
          auto_renewal: true
        })
        store.showNotification('Certificado SSL creado exitosamente', 'success')
        showForm.value = false
        await loadSSL()
        emit('reload')
      } catch (error) {
        store.showNotification('Error al crear certificado: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const renewSSL = async () => {
      loading.value = true
      try {
        await api.createSSL(props.domain.id, {
          domain_name: props.domain.domain_name,
          auto_renewal: true
        })
        store.showNotification('Certificado renovado exitosamente', 'success')
        await loadSSL()
      } catch (error) {
        store.showNotification('Error al renovar certificado: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const revokeSSL = async () => {
      loading.value = true
      try {
        await api.deleteSSL(props.domain.id)
        store.showNotification('Certificado SSL revocado', 'success')
        ssl.value = null
        showRevokeConfirm.value = false
        emit('reload')
      } catch (error) {
        store.showNotification('Error al revocar certificado: ' + error.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const formatDate = (date) => {
      if (!date) return 'N/A'
      return new Date(date).toLocaleDateString('es-ES')
    }

    onMounted(loadSSL)

    return {
      ssl,
      loading,
      showForm,
      showRevokeConfirm,
      createSSL,
      renewSSL,
      revokeSSL,
      formatDate
    }
  }
}
</script>

<style scoped>
.ssl-info {
  padding: 1rem;
  border-radius: 0.5rem;
  background-color: #f8f9fa;
}

.ssl-form {
  padding: 1rem;
  border-radius: 0.5rem;
  background-color: #f0f8ff;
  border-left: 4px solid #0d6efd;
}
</style>
