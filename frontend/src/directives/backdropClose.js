/**
 * v-backdrop-close="fn" — cierra un modal al hacer clic en su FONDO.
 *
 * Sustituye a `@click.self="fn"`, que tenía un fallo: si seleccionas texto en un
 * campo del formulario arrastrando y SUELTAS el ratón fuera del recuadro, el
 * navegador dispara el `click` sobre el ancestro común (el fondo) y el modal se
 * cerraba perdiendo lo escrito. Aquí solo se cierra si el clic EMPIEZA
 * (mousedown) y TERMINA (click) en el propio fondo.
 *
 * Uso: v-backdrop-close="closeForm"  ·  v-backdrop-close="() => show = false"
 */
export default {
  mounted(el, binding) {
    el._bdFn = binding.value
    el._bdDown = (e) => { el._bdStart = e.target === el }
    el._bdClick = (e) => {
      const ok = e.target === el && el._bdStart
      el._bdStart = false
      if (ok && typeof el._bdFn === 'function') el._bdFn(e)
    }
    el.addEventListener('mousedown', el._bdDown)
    el.addEventListener('click', el._bdClick)
  },
  updated(el, binding) {
    el._bdFn = binding.value
  },
  unmounted(el) {
    el.removeEventListener('mousedown', el._bdDown)
    el.removeEventListener('click', el._bdClick)
  },
}
