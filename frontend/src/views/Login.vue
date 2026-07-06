<template>
  <div class="login-page">
    <!-- Fondo decorativo con gradientes -->
    <div class="login-bg"></div>

    <div class="login-container">
      <!-- Card principal -->
      <div class="login-card">
        <!-- Cabecera: logo + título -->
        <div class="login-header">
          <div class="login-logo">
            <img v-if="branding?.has_logo" class="login-logo__img" :src="brandLogoUrl" :alt="brandName" />
            <span v-else-if="branding" class="login-logo__custom">{{ brandName }}</span>
            <template v-else>
              <span class="login-logo__svq">SVQ</span><span class="login-logo__panel">Panel</span>
            </template>
          </div>
          <h1 class="login-title">Bienvenido</h1>
          <p class="login-subtitle">Panel de control de servidores</p>
        </div>

        <!-- Paso 1: credenciales -->
        <form v-if="!twoFARequired" @submit.prevent="handleLogin" class="login-form">
          <div class="form-group">
            <label for="username">Usuario</label>
            <input
              id="username"
              v-model="credentials.username"
              type="text"
              class="form-control"
              placeholder="Tu usuario"
              required
              autofocus
            />
          </div>

          <div class="form-group">
            <label for="password">Contraseña</label>
            <input
              id="password"
              v-model="credentials.password"
              type="password"
              class="form-control"
              placeholder="Tu contraseña"
              required
            />
          </div>

          <div v-if="error" class="login-alert login-alert--error">
            <i class="bi bi-exclamation-circle-fill"></i>
            {{ error }}
          </div>

          <button
            type="submit"
            class="btn btn-primary login-btn"
            :disabled="loading"
          >
            <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
            {{ loading ? 'Autenticando…' : 'Iniciar sesión' }}
          </button>
        </form>

        <!-- Paso 2: 2FA -->
        <form v-else @submit.prevent="handleVerify2FA" class="login-form">
          <div class="login-2fa-icon">
            <i class="bi bi-shield-lock"></i>
          </div>
          <p class="login-2fa-text">
            Introduce el código de 6 dígitos de tu aplicación autenticadora.
          </p>

          <div class="form-group">
            <label for="totpCode">Código de verificación</label>
            <input
              id="totpCode"
              v-model="totpCode"
              type="text"
              inputmode="numeric"
              pattern="[0-9]{6}"
              maxlength="6"
              class="form-control login-totp-input"
              placeholder="000000"
              required
              autocomplete="one-time-code"
              ref="totpInput"
            />
          </div>

          <div v-if="error" class="login-alert login-alert--error">
            <i class="bi bi-exclamation-circle-fill"></i>
            {{ error }}
          </div>

          <button
            type="submit"
            class="btn btn-primary login-btn"
            :disabled="loading || totpCode.length !== 6"
          >
            <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
            {{ loading ? 'Verificando…' : 'Verificar código' }}
          </button>

          <button
            type="button"
            class="btn btn-link login-back"
            @click="cancelTwoFA"
          >
            <i class="bi bi-arrow-left me-1"></i> Volver al login
          </button>
        </form>

        <!-- Footer -->
        <div class="login-footer">
          <p>{{ footerText }}</p>
          <p v-if="branding?.support_url || branding?.support_email" class="login-footer__support">
            <a v-if="branding.support_url" :href="branding.support_url" target="_blank" rel="noopener">Soporte</a>
            <a v-if="branding.support_email" :href="'mailto:' + branding.support_email">{{ branding.support_email }}</a>
          </p>
        </div>
      </div>

      <!-- Marca derecha (decorativa) -->
      <div class="login-mark-right"></div>
    </div>
  </div>
</template>

<script>
import { ref, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../stores/useMainStore'
import api from '../services/api'

export default {
  name: 'Login',
  setup() {
    const router = useRouter()
    const store = useMainStore()
    const credentials = ref({ username: '', password: '' })
    const loading       = ref(false)
    const error         = ref(null)
    const twoFARequired = ref(false)
    const tempToken     = ref(null)
    const totpCode      = ref('')
    const totpInput     = ref(null)

    // ── Marca blanca ──
    const branding = computed(() => store.branding)
    const brandName = computed(() => branding.value?.panel_name || 'SVQPanel')
    const brandLogoUrl = computed(() =>
      `/api/branding/logo?v=${encodeURIComponent(branding.value?.version || '0')}`)
    const footerText = computed(() => {
      const year = new Date().getFullYear()
      if (!branding.value) return `SVQPanel © ${year}`
      const base = `${brandName.value} © ${year}`
      return branding.value.hide_powered_by ? base : `${base} · powered by SVQPanel`
    })

    const _storeSession = (response) => {
      localStorage.setItem('token', response.access_token)
      localStorage.setItem('user', JSON.stringify({
        id:       response.user_id,
        username: response.username,
        email:    response.email,
        role:     response.role,
        is_admin: response.is_admin,
      }))
      store.setCurrentUser({
        id:       response.user_id,
        username: response.username,
        email:    response.email,
        role:     response.role,
        is_admin: response.is_admin,
      })
      store.setToken(response.access_token)
    }

    const handleLogin = async () => {
      error.value   = null
      loading.value = true
      try {
        const response = await api.login(credentials.value)
        if (response.requires_2fa) {
          tempToken.value     = response.temp_token
          twoFARequired.value = true
          totpCode.value      = ''
          await nextTick()
          totpInput.value?.focus()
        } else {
          _storeSession(response)
          await router.push('/dashboard')
          store.showNotification(`¡Bienvenido ${response.username}!`, 'success')
        }
      } catch (err) {
        error.value = err.message || 'Error al iniciar sesión'
        store.showNotification(error.value, 'danger')
      } finally {
        loading.value = false
      }
    }

    const handleVerify2FA = async () => {
      if (totpCode.value.length !== 6) return
      error.value   = null
      loading.value = true
      try {
        const response = await api.verify2FA(tempToken.value, totpCode.value)
        _storeSession(response)
        await router.push('/dashboard')
        store.showNotification(`¡Bienvenido ${response.username}!`, 'success')
      } catch (err) {
        error.value    = err.message || 'Código incorrecto'
        totpCode.value = ''
        await nextTick()
        totpInput.value?.focus()
      } finally {
        loading.value = false
      }
    }

    const cancelTwoFA = () => {
      twoFARequired.value = false
      tempToken.value     = null
      totpCode.value      = ''
      error.value         = null
    }

    return {
      credentials,
      loading,
      error,
      twoFARequired,
      totpCode,
      totpInput,
      handleLogin,
      handleVerify2FA,
      cancelTwoFA,
      branding,
      brandName,
      brandLogoUrl,
      footerText,
    }
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  background: var(--bg);
}

.login-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(900px at 15% 20%, rgba(240,138,42,.08), transparent 45%),
    radial-gradient(800px at 85% 80%, rgba(26,37,71,.12), transparent 45%);
  pointer-events: none;
  z-index: 0;
}

.login-container {
  position: relative;
  z-index: 10;
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  max-width: 450px;
  padding: 20px;
}

.login-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  width: 100%;
  padding: 40px 36px;
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -.01em;
  margin-bottom: 12px;
  display: inline-block;
}

.login-logo__svq {
  color: var(--svq-navy);
}

.login-logo__panel {
  color: var(--svq-orange);
}

/* Marca blanca */
.login-logo__img {
  max-height: 56px;
  max-width: 260px;
  object-fit: contain;
}

.login-logo__custom {
  color: var(--text);
}

.login-footer__support {
  margin-top: 6px !important;
  display: flex;
  justify-content: center;
  gap: 14px;
}

.login-footer__support a {
  color: var(--ac-link);
  text-decoration: none;
  font-size: 12px;
}

.login-footer__support a:hover {
  text-decoration: underline;
}

.login-title {
  margin: 0 0 4px;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -.01em;
  color: var(--text);
}

.login-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.login-form {
  margin-bottom: 16px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.form-control {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text);
  background: var(--surface);
  transition: border-color .15s, box-shadow .15s;
}

.form-control::placeholder {
  color: var(--text-muted);
}

.form-control:focus {
  outline: none;
  border-color: var(--ac);
  box-shadow: 0 0 0 3px rgba(240,138,42,.25);
}

.login-totp-input {
  text-align: center;
  font-size: 18px;
  letter-spacing: 4px;
  font-family: var(--font-mono);
  font-weight: 600;
}

.login-btn {
  width: 100%;
  padding: 12px;
  font-size: 14px;
  font-weight: 600;
  background: var(--ac);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all .15s;
}

.login-btn:hover:not(:disabled) {
  background: #d97418;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.login-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.login-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  margin-bottom: 16px;
}

.login-alert--error {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}

.login-alert i {
  flex-shrink: 0;
  font-size: 16px;
}

.login-2fa-icon {
  text-align: center;
  margin-bottom: 16px;
}

.login-2fa-icon i {
  font-size: 40px;
  color: var(--ac);
}

.login-2fa-text {
  text-align: center;
  margin: 0 0 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.login-back {
  width: 100%;
  padding: 10px;
  margin-top: 12px;
  color: var(--text-secondary) !important;
  font-size: 13px;
  text-decoration: none;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: all .15s;
}

.login-back:hover {
  background: var(--surface-inset);
  color: var(--text) !important;
  border-color: var(--border-strong);
}

.login-footer {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
  text-align: center;
}

.login-footer p {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.login-mark-right {
  position: absolute;
  right: -120px;
  top: -80px;
  width: 400px;
  height: 400px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(240,138,42,.06), transparent 70%);
  pointer-events: none;
  z-index: 0;
}

@media (max-width: 480px) {
  .login-card {
    padding: 28px 20px;
  }
  .login-header {
    margin-bottom: 24px;
  }
  .login-title {
    font-size: 22px;
  }
}
</style>
