/**
 * Formateo de fechas centralizado del panel.
 *
 * El backend guarda datetime.utcnow() NAIVE (sin zona) y FastAPI lo serializa
 * sin la 'Z' final, así que un `new Date(iso)` a pelo lo interpreta como hora
 * local y sale desplazado. Aquí:
 *   1. Las cadenas ISO sin zona se interpretan como UTC.
 *   2. Se muestran en la zona horaria CONFIGURADA EN EL PANEL (Ajustes →
 *      Zona horaria), no en la del navegador. Fallback: zona del navegador.
 */

let panelTz = localStorage.getItem('panelTz') || null

/** Carga la zona configurada desde el backend y la cachea. Llamar tras login
 *  y al arrancar la app con sesión. */
export async function loadPanelTimezone(api) {
  try {
    const r = await api.get('/api/settings/timezone')
    if (r && r.timezone) {
      panelTz = r.timezone
      localStorage.setItem('panelTz', panelTz)
    }
  } catch { /* sin sesión o backend viejo: se usa la zona del navegador */ }
}

export function getPanelTimezone() { return panelTz }

/** Convierte lo que manda el backend a Date. Acepta Date, epoch (s o ms) y
 *  cadenas ISO; las ISO sin zona se tratan como UTC. */
export function toDate(dt) {
  if (dt == null || dt === '') return null
  if (dt instanceof Date) return isNaN(dt) ? null : dt
  if (typeof dt === 'number') return new Date(dt > 1e12 ? dt : dt * 1000)
  if (typeof dt !== 'string') return null
  let s = dt.trim()
  // "2026-07-02 21:50:57" → forma ISO con T (Safari no traga el espacio)
  if (/^\d{4}-\d{2}-\d{2} \d/.test(s)) s = s.replace(' ', 'T')
  // ISO con hora y sin zona = UTC naive del backend → añadir Z
  if (/^\d{4}-\d{2}-\d{2}T/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (!isNaN(d)) return d
  const raw = new Date(dt)   // último intento con la cadena original
  return isNaN(raw) ? null : raw
}

function fmt(dt, options) {
  const d = toDate(dt)
  if (!d) return '—'
  try {
    return d.toLocaleString('es-ES', { timeZone: panelTz || undefined, ...options })
  } catch {
    // panelTz corrupta/no soportada por el navegador
    return d.toLocaleString('es-ES', options)
  }
}

/** «02 jul 2026, 23:51» — el formato por defecto para timestamps. */
export const formatDateTime = (dt) =>
  fmt(dt, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/** «02 jul 2026, 23:51:07» — cuando los segundos importan (auditoría, logs). */
export const formatDateTimeSec = (dt) =>
  fmt(dt, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })

/** «02 jul 2026» — solo fecha. */
export const formatDate = (dt) =>
  fmt(dt, { day: '2-digit', month: 'short', year: 'numeric' })

/** «23:51» — solo hora (ticks de gráficas, etc.). */
export const formatTime = (dt) =>
  fmt(dt, { hour: '2-digit', minute: '2-digit' })

/** «2026-07-05» — el día de HOY (± offsetDays) en la zona horaria del PANEL.
 *  Para selectores de fecha: nunca usar new Date().toISOString() (eso es UTC:
 *  a las 00:09 en Madrid aún diría "ayer"). 'en-CA' formatea como YYYY-MM-DD. */
export function dayISO(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000)
  try {
    return d.toLocaleDateString('en-CA', { timeZone: panelTz || undefined })
  } catch {
    return d.toLocaleDateString('en-CA')   // panelTz corrupta: zona del navegador
  }
}
