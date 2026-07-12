import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/tokens.css'
// Bootstrap ya NO se carga: ni su CSS ni su JS. Del CDN solo vienen los iconos
// (bi-*). El estilo del panel lo dan estos tres ficheros, y el ORDEN importa:
//
//   tokens  → variables (color, tipografía, espaciado, radios, sombras)
//   compat  → las utilidades que aportaba Bootstrap, reescritas: grid (row/col),
//             flex, spacing (mb-3, me-1…), display, tipografía, spinner…
//   bridge  → reestiliza con los tokens los componentes tipo Bootstrap que aún
//             usan las vistas (.card, .btn, .table, .badge, .form-control…).
//             Va DESPUÉS de compat a propósito: en las 14 clases que ambos
//             tocan, gana el bridge (es quien las adapta al diseño del panel).
//
// OJO: compat llevaba sin importarse desde que se retiró Bootstrap, así que 84
// clases (row, col-md-6, d-flex, justify-content-between, mb-3, me-1, text-center,
// fw-bold, spinner-border…) NO tenían definición: el grid y las utilidades del
// panel estaban rotos en producción y nadie lo había atado al síntoma.
import './assets/bootstrap-compat.css'
import './assets/bootstrap-bridge.css'
import App from './App.vue'
import router from './router'
import { useMainStore } from './stores/useMainStore'

// Aplicar el tema guardado antes de montar para evitar el flash de color
const savedTheme = localStorage.getItem('theme') || 'light'
document.documentElement.dataset.theme = savedTheme

const app = createApp(App)

app.use(createPinia())
app.use(router)

// Cargar la marca blanca (endpoint público) antes de montar para evitar el
// flash de la marca por defecto. Si la API tarda >1s, montamos igualmente
// y la marca se aplica cuando llegue.
const store = useMainStore()
Promise.race([
  store.loadBranding(),
  new Promise(resolve => setTimeout(resolve, 1000)),
]).finally(() => app.mount('#app'))
