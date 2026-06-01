<template>
  <transition name="cmdk">
    <div v-if="open" class="cmdk-overlay" @click.self="close">
      <div class="cmdk" role="dialog" aria-modal="true">
        <div class="cmdk__input-wrap">
          <i class="bi bi-search"></i>
          <input
            ref="inputEl"
            v-model="query"
            class="cmdk__input"
            type="text"
            placeholder="Buscar páginas y acciones…"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="runActive"
            @keydown.esc.prevent="close"
          />
          <kbd class="cmdk__esc">ESC</kbd>
        </div>

        <div class="cmdk__results" ref="resultsEl">
          <template v-if="filtered.length">
            <div v-for="group in grouped" :key="group.label" class="cmdk__group">
              <p class="cmdk__group-label">{{ group.label }}</p>
              <button
                v-for="item in group.items"
                :key="item._id"
                class="cmdk__item"
                :class="{ active: item._index === activeIndex }"
                @click="runItem(item)"
                @mousemove="activeIndex = item._index"
              >
                <span class="cmdk__item-icon"><i class="bi" :class="`bi-${item.icon}`"></i></span>
                <span class="cmdk__item-label">{{ item.label }}</span>
                <span v-if="item.hint" class="cmdk__item-hint">{{ item.hint }}</span>
                <i class="bi bi-arrow-return-left cmdk__item-enter"></i>
              </button>
            </div>
          </template>
          <div v-else class="cmdk__empty">
            <i class="bi bi-search"></i>
            <p>Sin resultados para «{{ query }}»</p>
          </div>
        </div>

        <div class="cmdk__footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> navegar</span>
          <span><kbd>↵</kbd> abrir</span>
          <span><kbd>esc</kbd> cerrar</span>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMainStore } from '../../stores/useMainStore'
import api from '../../services/api'

export default {
  name: 'CommandPalette',
  setup() {
    const router = useRouter()
    const store = useMainStore()
    const open = ref(false)
    const query = ref('')
    const activeIndex = ref(0)
    const inputEl = ref(null)
    const resultsEl = ref(null)
    const domains = ref([])
    const domainsLoaded = ref(false)

    const user = computed(() => store.currentUser || {})
    const can = (roles) => {
      if (!roles) return true
      return roles.some((r) => {
        if (r === 'admin') return user.value.is_admin
        if (r === 'notAdmin') return !user.value.is_admin
        return user.value.role === r
      })
    }

    // Catálogo de comandos: navegación + acciones
    const catalog = computed(() => [
      // Navegación
      { group: 'Ir a', label: 'Dashboard', icon: 'speedometer2', to: '/dashboard', keywords: 'inicio resumen' },
      { group: 'Ir a', label: 'Dominios', icon: 'globe2', to: '/domains', keywords: 'sitios web' },
      { group: 'Ir a', label: 'Bases de datos', icon: 'database', to: '/databases', keywords: 'mariadb mysql bd' },
      { group: 'Ir a', label: 'Correo', icon: 'envelope', to: '/mail', keywords: 'email buzones mail' },
      { group: 'Ir a', label: 'DNS', icon: 'diagram-3', to: '/dns', keywords: 'zonas registros bind' },
      { group: 'Ir a', label: 'Archivos', icon: 'folder2-open', to: '/files', keywords: 'ficheros file manager' },
      { group: 'Ir a', label: 'Acceso SFTP', icon: 'folder-symlink', to: '/sftp', keywords: 'sftp ssh', roles: ['notAdmin'] },
      { group: 'Ir a', label: 'Tareas Cron', icon: 'clock-history', to: '/crons', keywords: 'cron programadas' },
      { group: 'Ir a', label: 'Copias de seguridad', icon: 'hdd-stack', to: '/backups', keywords: 'backup respaldo' },
      { group: 'Ir a', label: 'Usuarios', icon: 'people', to: '/users', keywords: 'clientes cuentas', roles: ['admin'] },
      { group: 'Ir a', label: 'Planes', icon: 'stack', to: '/plans', keywords: 'planes limites', roles: ['admin', 'reseller'] },
      { group: 'Ir a', label: 'Gestión de IPs', icon: 'hdd-network', to: '/server-ips', keywords: 'ip ipv4 ipv6', roles: ['admin'] },
      { group: 'Ir a', label: 'Servicios', icon: 'hdd-rack', to: '/system', keywords: 'nginx php-fpm sistema', roles: ['admin'] },
      { group: 'Ir a', label: 'Seguridad', icon: 'shield-lock', to: '/security', keywords: 'firewall fail2ban crowdsec', roles: ['admin'] },
      { group: 'Ir a', label: 'Actualizaciones', icon: 'arrow-repeat', to: '/system/updates', keywords: 'updates apt', roles: ['admin'] },
      { group: 'Ir a', label: 'Configuración', icon: 'gear', to: '/settings', keywords: 'ajustes config', roles: ['admin'] },
      // Acciones rápidas
      { group: 'Acciones', label: 'Crear dominio', icon: 'plus-lg', to: '/domains', keywords: 'nuevo dominio añadir', hint: 'Dominios' },
      { group: 'Acciones', label: 'Nueva base de datos', icon: 'plus-lg', to: '/databases', keywords: 'crear bd', hint: 'Bases de datos' },
      { group: 'Acciones', label: 'Nueva zona DNS', icon: 'plus-lg', to: '/dns', keywords: 'crear zona dns', hint: 'DNS' },
      { group: 'Acciones', label: 'Cambiar tema claro/oscuro', icon: 'circle-half', action: () => store.toggleTheme(), keywords: 'modo oscuro dark light tema' },
      { group: 'Acciones', label: 'Cerrar sesión', icon: 'box-arrow-right', action: () => doLogout(), keywords: 'salir logout' },
      // Dominios cargados dinámicamente (saltan al detalle)
      ...domains.value.map((d) => ({
        group: 'Dominios', label: d.domain_name, icon: 'globe2',
        to: `/domains/${d.id}`, keywords: 'dominio sitio web ' + d.domain_name,
        hint: d.ssl_enabled ? 'SSL' : '',
      })),
    ].filter((c) => can(c.roles)))

    const filtered = computed(() => {
      const q = query.value.trim().toLowerCase()
      const base = !q ? catalog.value : catalog.value.filter((c) =>
        (c.label + ' ' + (c.keywords || '')).toLowerCase().includes(q))
      // asignar índice plano para navegación con teclado
      return base.map((c, i) => ({ ...c, _index: i, _id: c.group + c.label }))
    })

    const grouped = computed(() => {
      const groups = []
      for (const item of filtered.value) {
        let g = groups.find((x) => x.label === item.group)
        if (!g) { g = { label: item.group, items: [] }; groups.push(g) }
        g.items.push(item)
      }
      return groups
    })

    const doLogout = async () => {
      close()
      store.logout()
      store.showNotification('Sesión cerrada', 'success')
      router.push('/login')
    }

    const loadDomains = async () => {
      if (domainsLoaded.value) return
      domainsLoaded.value = true
      try {
        const data = await api.getDomains(null, 0, 200)
        domains.value = Array.isArray(data) ? data : []
      } catch { /* silencioso: el palette funciona sin dominios */ }
    }

    const openPalette = async () => {
      open.value = true
      query.value = ''
      activeIndex.value = 0
      loadDomains()
      await nextTick()
      inputEl.value?.focus()
    }
    const close = () => { open.value = false }

    const move = (delta) => {
      const n = filtered.value.length
      if (!n) return
      activeIndex.value = (activeIndex.value + delta + n) % n
      scrollToActive()
    }
    const scrollToActive = () => {
      nextTick(() => {
        const el = resultsEl.value?.querySelector('.cmdk__item.active')
        el?.scrollIntoView({ block: 'nearest' })
      })
    }

    const runItem = (item) => {
      if (item.action) { item.action(); if (!item.keepOpen) close() }
      else if (item.to) { router.push(item.to); close() }
    }
    const runActive = () => {
      const item = filtered.value[activeIndex.value]
      if (item) runItem(item)
    }

    watch(query, () => { activeIndex.value = 0 })

    const onKeydown = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        open.value ? close() : openPalette()
      }
    }

    onMounted(() => {
      document.addEventListener('keydown', onKeydown)
      window.addEventListener('svq:open-command-palette', openPalette)
    })
    onUnmounted(() => {
      document.removeEventListener('keydown', onKeydown)
      window.removeEventListener('svq:open-command-palette', openPalette)
    })

    return { open, query, activeIndex, inputEl, resultsEl, filtered, grouped, move, runActive, runItem, close }
  },
}
</script>

<style scoped>
.cmdk-overlay {
  position: fixed; inset: 0;
  background: rgba(10, 12, 20, 0.5);
  backdrop-filter: blur(4px);
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 12vh; z-index: 2000;
}
.cmdk {
  width: 100%; max-width: 600px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex; flex-direction: column;
}
.cmdk__input-wrap {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border);
}
.cmdk__input-wrap > .bi { color: var(--text-muted); font-size: 18px; }
.cmdk__input {
  flex: 1; border: none; background: transparent; outline: none;
  font-size: var(--fs-lg); color: var(--text); font-family: var(--font-sans);
}
.cmdk__input::placeholder { color: var(--text-muted); }
.cmdk__esc {
  font-family: var(--font-sans); font-size: 11px;
  background: var(--surface-inset); border: 1px solid var(--border);
  border-radius: 6px; padding: 2px 7px; color: var(--text-muted);
}

.cmdk__results { max-height: 50vh; overflow-y: auto; padding: var(--sp-2); }
.cmdk__group { margin-bottom: var(--sp-2); }
.cmdk__group-label {
  margin: var(--sp-2) var(--sp-3) 4px;
  font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em;
  color: var(--text-muted); font-weight: var(--fw-semibold);
}
.cmdk__item {
  display: flex; align-items: center; gap: var(--sp-3);
  width: 100%; padding: 9px var(--sp-3);
  border: none; background: transparent; cursor: pointer;
  border-radius: var(--r-md); color: var(--text); text-align: left;
}
.cmdk__item.active { background: var(--brand-50); color: var(--color-primary); }
[data-theme="dark"] .cmdk__item.active { background: var(--surface-2); color: var(--brand-400); }
.cmdk__item-icon { width: 24px; display: grid; place-items: center; font-size: 15px; color: var(--text-muted); }
.cmdk__item.active .cmdk__item-icon { color: inherit; }
.cmdk__item-label { flex: 1; font-size: var(--fs-base); font-weight: var(--fw-medium); }
.cmdk__item-hint { font-size: var(--fs-sm); color: var(--text-muted); }
.cmdk__item-enter { opacity: 0; font-size: 13px; }
.cmdk__item.active .cmdk__item-enter { opacity: .7; }

.cmdk__empty { text-align: center; padding: var(--sp-8); color: var(--text-muted); }
.cmdk__empty .bi { font-size: 28px; opacity: .5; }
.cmdk__empty p { margin: var(--sp-2) 0 0; font-size: var(--fs-sm); }

.cmdk__footer {
  display: flex; gap: var(--sp-4);
  padding: var(--sp-2) var(--sp-5);
  border-top: 1px solid var(--border);
  background: var(--surface-2);
  font-size: var(--fs-xs); color: var(--text-muted);
}
.cmdk__footer kbd {
  font-family: var(--font-sans); background: var(--surface); border: 1px solid var(--border);
  border-radius: 4px; padding: 0 5px; margin-right: 2px; color: var(--text-secondary);
}

.cmdk-enter-active, .cmdk-leave-active { transition: opacity var(--t-base) var(--ease); }
.cmdk-enter-active .cmdk, .cmdk-leave-active .cmdk { transition: transform var(--t-base) var(--ease-out), opacity var(--t-base); }
.cmdk-enter-from, .cmdk-leave-to { opacity: 0; }
.cmdk-enter-from .cmdk, .cmdk-leave-to .cmdk { transform: scale(.97) translateY(-8px); }
</style>
