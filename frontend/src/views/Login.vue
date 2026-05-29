<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <div class="login-mark"><i class="bi bi-hexagon-fill"></i></div>
        <h1>SVQPanel</h1>
        <p class="version">Panel de control · v0.1.0</p>
      </div>

      <!-- ── Paso 1: usuario + contraseña ── -->
      <form v-if="!twoFARequired" @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="username">Usuario</label>
          <input
            id="username"
            v-model="credentials.username"
            type="text"
            class="form-control"
            placeholder="Ingresa tu usuario"
            required
          />
        </div>

        <div class="form-group">
          <label for="password">Contraseña</label>
          <input
            id="password"
            v-model="credentials.password"
            type="password"
            class="form-control"
            placeholder="Ingresa tu contraseña"
            required
          />
        </div>

        <div v-if="error" class="alert alert-danger">
          <i class="bi bi-exclamation-circle"></i> {{ error }}
        </div>

        <button
          type="submit"
          class="btn btn-primary btn-login"
          :disabled="loading"
        >
          <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
          {{ loading ? 'Autenticando...' : 'Iniciar Sesión' }}
        </button>
      </form>

      <!-- ── Paso 2: código TOTP ── -->
      <form v-else @submit.prevent="handleVerify2FA" class="login-form">
        <div class="twofa-icon text-center mb-3">
          <i class="bi bi-shield-lock-fill text-primary" style="font-size:2.5rem"></i>
        </div>
        <p class="text-center text-muted mb-3">
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
            class="form-control text-center"
            style="font-size:1.4rem; letter-spacing:0.3rem"
            placeholder="000000"
            required
            autocomplete="one-time-code"
            ref="totpInput"
          />
        </div>

        <div v-if="error" class="alert alert-danger">
          <i class="bi bi-exclamation-circle"></i> {{ error }}
        </div>

        <button
          type="submit"
          class="btn btn-primary btn-login"
          :disabled="loading || totpCode.length !== 6"
        >
          <span v-if="loading" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
          {{ loading ? 'Verificando...' : 'Verificar código' }}
        </button>

        <button type="button" class="btn btn-link w-100 mt-2 text-muted" @click="cancelTwoFA">
          <i class="bi bi-arrow-left me-1"></i> Volver al login
        </button>
      </form>

      <div class="login-footer">
        <p class="text-muted">SVQPanel © 2026 - Panel de Control de Servidores</p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, nextTick } from 'vue'
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
          // Guardar token temporal y mostrar paso 2FA
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
    }
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: var(--sp-4);
  font-family: var(--font-sans);
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(900px circle at 15% 20%, rgba(99,102,241,.18), transparent 45%),
    radial-gradient(800px circle at 85% 80%, rgba(67,56,202,.20), transparent 45%),
    var(--bg);
}
/* malla sutil de fondo */
.login-container::before {
  content: '';
  position: absolute; inset: 0;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 48px 48px;
  opacity: .35;
  mask-image: radial-gradient(ellipse at center, black, transparent 75%);
}

.login-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg);
  width: 100%;
  max-width: 410px;
  padding: var(--sp-10) var(--sp-8);
}

.login-header { text-align: center; margin-bottom: var(--sp-8); }
.login-mark {
  width: 54px; height: 54px; margin: 0 auto var(--sp-4);
  display: grid; place-items: center;
  border-radius: var(--r-lg);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff; font-size: 26px;
  box-shadow: 0 8px 24px rgba(79,70,229,.35);
}
.login-header h1 {
  margin: 0; font-size: var(--fs-2xl); font-weight: var(--fw-bold);
  letter-spacing: -.02em; color: var(--text);
}
.login-header .version { margin: var(--sp-1) 0 0; color: var(--text-muted); font-size: var(--fs-sm); }

.login-form { margin-bottom: var(--sp-4); }
.form-group { margin-bottom: var(--sp-4); }
.form-group label { display: block; margin-bottom: 6px; font-weight: var(--fw-medium); color: var(--text-secondary); font-size: var(--fs-sm); }

.form-control {
  width: 100%; padding: 11px var(--sp-3);
  border: 1px solid var(--border-strong); border-radius: var(--r-md);
  font-size: var(--fs-base); background: var(--surface); color: var(--text);
  transition: border-color var(--t-fast), box-shadow var(--t-fast);
}
.form-control::placeholder { color: var(--text-muted); }
.form-control:focus { outline: none; border-color: var(--color-primary); box-shadow: var(--shadow-focus); }

.btn-login {
  width: 100%; padding: 12px; font-size: var(--fs-md); font-weight: var(--fw-semibold);
  border: none; border-radius: var(--r-md);
  background: var(--color-primary); color: #fff; cursor: pointer;
  transition: transform var(--t-fast), background var(--t-fast), box-shadow var(--t-fast);
}
.btn-login:hover:not(:disabled) { background: var(--color-primary-hover); transform: translateY(-1px); box-shadow: var(--shadow-md); }
.btn-login:disabled { opacity: .6; cursor: not-allowed; }

.alert { margin-bottom: var(--sp-4); padding: var(--sp-3); border-radius: var(--r-md); font-size: var(--fs-sm); }
.alert-danger { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger-border); }

.login-footer { text-align: center; border-top: 1px solid var(--border); padding-top: var(--sp-5); margin-top: var(--sp-5); }
.login-footer .text-muted { margin: 0; font-size: var(--fs-sm); color: var(--text-muted); }
.twofa-icon .bi { color: var(--color-primary); }
</style>
