/**
 * Horario de un cron en lenguaje normal ↔ expresión de 5 campos.
 *
 * Modos sencillos (lo que entiende alguien sin conocimientos):
 *   minutes  → cada N minutos            (*\/N * * * *)
 *   hourly   → cada H horas en el min M  (M *\/H * * *)
 *   daily    → cada día a las HH:MM      (M H * * *)
 *   weekly   → ciertos días a las HH:MM  (M H * * 1,5)
 *   monthly  → el día D a las HH:MM      (M H D * *)
 *   advanced → los 5 campos a mano
 */

export const WEEKDAYS = [
  { v: 1, short: 'L', name: 'lunes' },
  { v: 2, short: 'M', name: 'martes' },
  { v: 3, short: 'X', name: 'miércoles' },
  { v: 4, short: 'J', name: 'jueves' },
  { v: 5, short: 'V', name: 'viernes' },
  { v: 6, short: 'S', name: 'sábados' },
  { v: 0, short: 'D', name: 'domingos' },
]
export const MINUTE_STEPS = [1, 2, 5, 10, 15, 20, 30]
export const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12]

const NUM = /^\d+$/
const pad = (n) => String(n).padStart(2, '0')

export function defaultSimple() {
  return { mode: 'hourly', every: 5, everyHours: 1, minute: 0, time: '03:00', days: [1], monthDay: 1 }
}

function splitTime(time) {
  const [h, m] = String(time || '00:00').split(':').map((x) => parseInt(x, 10) || 0)
  return [Math.min(Math.max(h, 0), 23), Math.min(Math.max(m, 0), 59)]
}

/** Modo sencillo → { minute, hour, day, month, weekday } */
export function fromSimple(s) {
  const [h, m] = splitTime(s.time)
  const all = { day: '*', month: '*', weekday: '*' }
  switch (s.mode) {
    case 'minutes':
      return { minute: s.every > 1 ? `*/${s.every}` : '*', hour: '*', ...all }
    case 'hourly':
      return { minute: String(Math.min(Math.max(parseInt(s.minute, 10) || 0, 0), 59)),
               hour: s.everyHours > 1 ? `*/${s.everyHours}` : '*', ...all }
    case 'daily':
      return { minute: String(m), hour: String(h), ...all }
    case 'weekly': {
      const days = [...new Set(s.days || [])].sort((a, b) => a - b)
      return { minute: String(m), hour: String(h), day: '*', month: '*', weekday: days.length ? days.join(',') : '*' }
    }
    case 'monthly':
      return { minute: String(m), hour: String(h), day: String(s.monthDay || 1), month: '*', weekday: '*' }
    default:
      return null
  }
}

/** Expresión → modo sencillo, o { mode: 'advanced' } si no encaja en ninguno. */
export function toSimple(c) {
  const s = defaultSimple()
  const { minute, hour, day, month, weekday } = c
  const stepOf = (f) => (f === '*' ? 1 : (/^\*\/(\d+)$/.exec(f) || [])[1] * 1)
  if (month !== '*') return { ...s, mode: 'advanced' }

  if (hour === '*' && day === '*' && weekday === '*') {
    const st = stepOf(minute)
    if (st && MINUTE_STEPS.includes(st)) return { ...s, mode: 'minutes', every: st }
  }
  if (NUM.test(minute) && day === '*' && weekday === '*') {
    const hs = stepOf(hour)
    if (hs && HOUR_STEPS.includes(hs)) return { ...s, mode: 'hourly', minute: +minute, everyHours: hs }
  }
  if (NUM.test(minute) && NUM.test(hour)) {
    const time = `${pad(hour)}:${pad(minute)}`
    if (day === '*' && weekday === '*') return { ...s, mode: 'daily', time }
    if (day === '*' && /^\d(,\d)*$/.test(weekday)) {
      const days = weekday.split(',').map((d) => (+d === 7 ? 0 : +d))
      return { ...s, mode: 'weekly', time, days }
    }
    if (NUM.test(day) && weekday === '*') return { ...s, mode: 'monthly', time, monthDay: +day }
  }
  return { ...s, mode: 'advanced' }
}

function listEs(items) {
  return items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' y ' + items[items.length - 1]
}

/** Descripción en castellano de una expresión (para la tabla y el formulario). */
export function describeCron(c) {
  if (!c) return ''
  const s = toSimple(c)
  const expr = `${c.minute} ${c.hour} ${c.day} ${c.month} ${c.weekday}`
  switch (s.mode) {
    case 'minutes':
      return s.every === 1 ? 'Cada minuto' : `Cada ${s.every} minutos`
    case 'hourly':
      if (s.everyHours === 1) return s.minute === 0 ? 'Cada hora' : `Cada hora, en el minuto ${s.minute}`
      return `Cada ${s.everyHours} horas, en el minuto ${s.minute}`
    case 'daily':
      return `Cada día a las ${s.time}`
    case 'weekly': {
      const set = new Set(s.days)
      if (set.size === 7) return `Cada día a las ${s.time}`
      if (set.size === 5 && [1, 2, 3, 4, 5].every((d) => set.has(d))) return `De lunes a viernes a las ${s.time}`
      if (set.size === 2 && set.has(6) && set.has(0)) return `Sábados y domingos a las ${s.time}`
      const names = WEEKDAYS.filter((w) => set.has(w.v)).map((w) => w.name)
      return `Los ${listEs(names)} a las ${s.time}`
    }
    case 'monthly':
      return `El día ${s.monthDay} de cada mes a las ${s.time}`
    default:
      return expr
  }
}
