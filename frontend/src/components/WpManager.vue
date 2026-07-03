<template>
  <BaseCard title="WordPress instalado" icon="wordpress">
    <template #actions>
      <BaseButton variant="ghost" size="sm" icon="arrow-clockwise" :loading="loadingInfo" @click="loadInfo">Refrescar</BaseButton>
    </template>

    <div v-if="errorInfo && !info" class="wpm-error"><i class="bi bi-exclamation-triangle"></i> {{ errorInfo }}</div>

    <template v-else>
      <!-- Resumen (solo cuando ya se analizó WP; no bloquea el resto) -->
      <div v-if="info" class="wpm-summary">
        <div class="wpm-stat"><span class="wpm-stat__k">Versión WP</span><span class="wpm-stat__v mono">{{ info.version || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Idioma</span><span class="wpm-stat__v">{{ info.locale || '—' }}</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Plugins</span><span class="wpm-stat__v">{{ info.plugins_active }}/{{ info.plugins_total }} activos</span></div>
        <div class="wpm-stat"><span class="wpm-stat__k">Temas</span><span class="wpm-stat__v">{{ info.themes_total }}</span></div>
      </div>
      <div v-else-if="loadingInfo" class="wpm-summary wpm-summary--loading">
        <div class="wpm-stat"><span class="wpm-stat__k">Analizando la instalación…</span><span class="wpm-stat__v"><span class="spinner"></span></span></div>
      </div>

      <!-- Avisos de actualización (independiente; solo se muestra si hay info) -->
      <div v-if="info && loadingUpdates && !info.updates.checked" class="wpm-uptodate">
        <span class="spinner"></span> Comprobando actualizaciones…
      </div>
      <div v-else-if="info && totalUpdates > 0" class="wpm-updbanner">
        <i class="bi bi-arrow-up-circle"></i>
        <span>Hay <strong>{{ totalUpdates }}</strong> actualización(es) pendiente(s):
          <template v-if="info.updates.core">core, </template>
          <template v-if="info.updates.plugins">{{ info.updates.plugins }} plugin(s), </template>
          <template v-if="info.updates.themes">{{ info.updates.themes }} tema(s)</template>
        </span>
      </div>
      <div v-else-if="info && info.updates.checked" class="wpm-uptodate"><i class="bi bi-check-circle"></i> Todo está actualizado.</div>

      <!-- Los tabs SIEMPRE visibles: no esperan al análisis de WP (que es lento).
           Cada pane carga lo suyo; Seguridad va a la BD y es instantáneo. -->
      <BaseTabs v-model="tab" :tabs="tabs" />

      <!-- ── Tab General (necesita info de WP) ── -->
      <div v-if="tab === 'general'" class="wpm-pane">
        <div v-if="!info" class="wpm-loading"><span class="spinner"></span> Analizando la instalación de WordPress…</div>
        <template v-else>
          <div class="wpm-actions">
            <BaseButton v-if="info.updates.core" variant="primary" size="sm" icon="arrow-up-circle" :loading="busy==='core'" @click="run('update-core', {}, 'core')">Actualizar WordPress</BaseButton>
            <a class="wpm-link" :href="adminUrl" target="_blank"><i class="bi bi-box-arrow-up-right"></i> Abrir wp-admin</a>
          </div>
          <div class="wpm-quick">
            <button class="wpm-qbtn" :disabled="!!busy" @click="run('flush-permalinks', {}, 'perma')"><i class="bi bi-link-45deg"></i> Regenerar permalinks</button>
            <button class="wpm-qbtn" :disabled="!!busy" @click="run('flush-cache', {}, 'cache')"><i class="bi bi-trash"></i> Vaciar caché</button>
            <button class="wpm-qbtn" :disabled="!!busy" @click="toggleMaintenance"><i class="bi bi-cone-striped"></i> {{ info.maintenance ? 'Quitar mantenimiento' : 'Modo mantenimiento' }}</button>
            <button class="wpm-qbtn" :class="{ 'wpm-qbtn--on': cronOptimized }" :disabled="!!busy || !cronLoaded" @click="toggleCronOptimize"><i class="bi bi-speedometer2"></i> {{ cronBtnLabel }}</button>
            <button class="wpm-qbtn wpm-qbtn--warn" :disabled="!!busy" @click="confirmSalts"><i class="bi bi-shield-lock"></i> Regenerar claves (cierra sesiones)</button>
          </div>
        </template>
      </div>

      <!-- ── Tab Plugins / Temas ── -->
      <div v-else-if="tab === 'plugins' || tab === 'themes'" class="wpm-pane">
        <div class="wpm-itembar">
          <BaseButton variant="ghost" size="sm" icon="arrow-up-circle" :loading="busy==='updall'"
            @click="run('update-items', { kind: itemKind }, 'updall')">Actualizar todos</BaseButton>
          <span class="dd-muted">{{ items.length }} {{ itemKind === 'plugin' ? 'plugins' : 'temas' }}</span>
        </div>
        <div v-if="loadingItems" class="wpm-loading"><span class="spinner"></span> Cargando…</div>
        <table v-else class="wpm-table">
          <thead><tr><th>Nombre</th><th>Versión</th><th>Estado</th><th></th></tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.name">
              <td><span class="wpm-name">{{ it.title || it.name }}</span><br><span class="mono dd-muted">{{ it.name }}</span></td>
              <td class="mono">{{ it.version }}<br v-if="it.update==='available'"><span v-if="it.update==='available'" class="wpm-newver">→ {{ it.update_version }}</span></td>
              <td>
                <span class="wpm-badge" :class="it.status==='active' ? 'is-on' : 'is-off'">{{ statusLabel(it.status) }}</span>
              </td>
              <td class="wpm-rowactions">
                <button v-if="it.update==='available'" class="wpm-mini" :disabled="!!busy" @click="run('update-items', { kind: itemKind, name: it.name }, 'i:'+it.name)" title="Actualizar"><i class="bi bi-arrow-up-circle"></i></button>
                <button v-if="it.status==='active'" class="wpm-mini" :disabled="!!busy" @click="run('toggle-item', { kind: itemKind, name: it.name, activate: false }, 't:'+it.name)" title="Desactivar"><i class="bi bi-pause-circle"></i></button>
                <button v-else class="wpm-mini" :disabled="!!busy" @click="run('toggle-item', { kind: itemKind, name: it.name, activate: true }, 't:'+it.name)" title="Activar"><i class="bi bi-play-circle"></i></button>
                <button class="wpm-mini wpm-mini--danger" :disabled="!!busy || it.status==='active'" @click="deleteItem(it)" :title="it.status==='active' ? (itemKind==='theme' ? 'Activa otro tema antes de borrar' : 'Desactiva el plugin antes de borrar') : 'Eliminar'"><i class="bi bi-trash"></i></button>
              </td>
            </tr>
            <tr v-if="!items.length"><td colspan="4" class="dd-muted" style="text-align:center;padding:1rem">No hay {{ itemKind === 'plugin' ? 'plugins' : 'temas' }}.</td></tr>
          </tbody>
        </table>
      </div>

      <!-- ── Tab Acceso / Admin ── -->
      <div v-else-if="tab === 'access'" class="wpm-pane">
        <div class="wpm-actions">
          <BaseButton variant="ghost" size="sm" icon="people" :loading="loadingUsers" @click="loadAdmins">Cargar administradores</BaseButton>
        </div>
        <table v-if="admins.length" class="wpm-table">
          <thead><tr><th>Usuario</th><th>Email</th><th></th></tr></thead>
          <tbody>
            <tr v-for="u in admins" :key="u.ID">
              <td><span class="wpm-name">{{ u.user_login }}</span><br><span class="dd-muted">{{ u.display_name }}</span></td>
              <td class="mono">{{ u.user_email }}</td>
              <td class="wpm-rowactions">
                <button class="wpm-mini" :disabled="!!busy" @click="resetPw(u.user_login)" title="Resetear contraseña"><i class="bi bi-key"></i></button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="wpm-urlbox">
          <label class="app-field">
            <span>URL del sitio (siteurl / home)</span>
            <div class="wpm-urlrow">
              <input class="svq-input mono" v-model="newUrl" :placeholder="info.siteurl" />
              <BaseButton variant="primary" size="sm" :loading="busy==='url'" @click="changeUrl">Cambiar</BaseButton>
            </div>
          </label>
          <small class="dd-muted">Cuidado: cambiar la URL puede dejar el sitio inaccesible si no coincide con el dominio/DNS.</small>
        </div>

        <div v-if="resetResult" class="app-result">
          <p class="app-result__title"><i class="bi bi-check-circle-fill"></i> Contraseña actualizada</p>
          <div class="app-result__row"><span>Usuario</span><span class="mono">{{ resetResult.user_login }}</span></div>
          <div class="app-result__row"><span>Nueva contraseña</span><span class="mono">{{ resetResult.new_password }}</span></div>
        </div>
      </div>

      <!-- ── Tab Seguridad (anti fuerza bruta WordPress) ── -->
      <div v-else-if="tab === 'security'" class="wpm-pane">
        <!-- Aviso de ataque en curso (solo si está bajo ataque y sin proteger) -->
        <div v-if="attack && attack.under_attack" class="wpm-attack">
          <div class="wpm-attack__icon"><i class="bi bi-exclamation-octagon-fill"></i></div>
          <div class="wpm-attack__body">
            <strong>Tu WordPress está recibiendo un ataque de fuerza bruta.</strong>
            <p>
              En la última hora se han registrado
              <span v-if="attack.xmlrpc_hits >= attack.threshold"><b>{{ attack.xmlrpc_hits.toLocaleString() }}</b> intentos contra <code>xmlrpc.php</code></span>
              <span v-if="attack.xmlrpc_hits >= attack.threshold && attack.wplogin_hits >= attack.threshold"> y </span>
              <span v-if="attack.wplogin_hits >= attack.threshold"><b>{{ attack.wplogin_hits.toLocaleString() }}</b> contra <code>wp-login.php</code></span>.
              Activa la protección para cortarlo sin afectar a tu acceso.
            </p>
            <BaseButton variant="primary" size="sm" icon="shield-fill-check" :loading="busy==='wpprotect-all'" @click="enableAllProtection">
              Activar protección recomendada
            </BaseButton>
          </div>
        </div>

        <div class="wpm-sec">
          <!-- XML-RPC -->
          <div class="wpm-sec__row">
            <div class="wpm-sec__info">
              <span class="wpm-sec__title"><i class="bi bi-shield-lock"></i> Bloquear XML-RPC</span>
              <small class="dd-muted">
                <code>xmlrpc.php</code> casi no se usa hoy (lo sustituye la API REST). Bloquearlo
                corta los ataques de amplificación/fuerza bruta. Desactívalo solo si usas la app
                móvil de WordPress o Jetpack con publicación remota.
              </small>
            </div>
            <button type="button" class="wpm-toggle" :class="{ 'is-on': prot.xmlrpc_blocked }"
                    :disabled="!!busy" role="switch" :aria-checked="prot.xmlrpc_blocked"
                    @click="toggleXmlrpc(!prot.xmlrpc_blocked)">
              <span class="wpm-toggle__knob"></span>
            </button>
          </div>

          <!-- Rate-limit wp-login -->
          <div class="wpm-sec__row">
            <div class="wpm-sec__info">
              <span class="wpm-sec__title"><i class="bi bi-speedometer"></i> Limitar intentos de login</span>
              <small class="dd-muted">
                Limita las peticiones por minuto a <code>wp-login.php</code> desde una misma IP.
                Una persona necesita 1-2 intentos; un bot mete miles. Recomendado: <b>3/min</b>.
                0 = sin límite.
              </small>
            </div>
            <div class="wpm-sec__rl">
              <input type="number" min="0" max="600" class="svq-input" style="width:5rem" v-model.number="rlInput" :disabled="!!busy" />
              <span class="dd-muted">/min</span>
              <BaseButton variant="ghost" size="sm" :loading="busy==='wprl'" @click="saveRateLimit">Guardar</BaseButton>
            </div>
          </div>
        </div>

        <!-- Endurecimiento (hardening) con checklist -->
        <div class="wpm-harden">
          <div class="wpm-harden__head">
            <span class="wpm-sec__title"><i class="bi bi-shield-check"></i> Endurecer WordPress</span>
            <span v-if="hardening" class="wpm-harden__score" :class="{ 'is-full': hardening.score.ok === hardening.score.total }">{{ hardening.score.ok }}/{{ hardening.score.total }}</span>
            <BaseButton v-if="hardening && hardening.score.ok < hardening.score.total" variant="primary" size="sm" icon="shield-fill-check" :loading="busy==='harden'" @click="applyHardening">Aplicar todo</BaseButton>
          </div>
          <div v-if="hardeningLoading" class="dd-muted"><span class="spinner"></span> Analizando…</div>
          <ul v-else-if="hardening" class="wpm-harden__list">
            <li v-for="c in hardening.checks" :key="c.id" :class="{ 'is-ok': c.ok }">
              <i class="bi" :class="c.ok ? 'bi-check-circle-fill' : 'bi-exclamation-circle'"></i>
              <div>
                <span class="wpm-harden__label">{{ c.label }}</span>
                <small class="dd-muted">{{ c.desc }}</small>
              </div>
            </li>
          </ul>
        </div>
      </div>

      <!-- ── Tab Actualizaciones (safe-update: checkpoint + rollback) ── -->
      <div v-else-if="tab === 'updates'" class="wpm-pane">
        <div v-if="safeLoading && !safeData" class="wpm-loading"><span class="spinner"></span> Consultando…</div>
        <template v-else-if="safeData">
          <!-- Actualización en curso -->
          <div v-if="safeJob && safeJob.status === 'running'" class="wpm-stgjob">
            <p class="wpm-stgjob__title"><span class="spinner"></span> Actualizando con protección…</p>
            <ul class="wpm-stgsteps">
              <li v-for="(s, i) in safeJob.steps" :key="i"
                  :class="{ 'is-done': i < safeJob.current, 'is-current': i === safeJob.current }">
                <i class="bi" :class="i < safeJob.current ? 'bi-check-circle-fill' : (i === safeJob.current ? 'bi-arrow-repeat' : 'bi-circle')"></i>
                {{ s }}
              </li>
            </ul>
            <small class="dd-muted">Si el sitio se rompe con la actualización, se restaurará solo el punto de recuperación. Puedes salir de esta página: la operación sigue en el servidor.</small>
          </div>

          <template v-else>
            <div v-if="safeJob && safeJob.status === 'failed' && safeJob.rolled_back" class="wpm-stgfail">
              <i class="bi bi-arrow-counterclockwise"></i> La actualización rompió el sitio y se restauró el punto de recuperación: {{ safeJob.error }}
            </div>
            <div v-else-if="safeJob && safeJob.status === 'failed'" class="wpm-stgfail">
              <i class="bi bi-exclamation-triangle"></i> La última actualización falló: {{ safeJob.error }}
            </div>

            <p class="wpm-sec__title"><i class="bi bi-shield-check"></i> Actualización segura</p>
            <p class="dd-muted" style="margin:.25rem 0 .9rem; line-height:1.5">
              Actualiza el core, los plugins y los temas con red de seguridad: antes se crea un
              punto de restauración (archivos + base de datos) y después se verifica que el sitio
              sigue funcionando. Si la actualización lo rompe, se restaura solo y el sitio queda
              como estaba.
            </p>
            <div class="wpm-actions">
              <BaseButton variant="primary" icon="shield-check" :loading="busy==='safe-run'" :disabled="!!busy" @click="runSafeUpdate">Actualizar con protección</BaseButton>
            </div>

            <div class="wpm-sec__row" style="margin-top:1rem">
              <div class="wpm-sec__info">
                <span class="wpm-sec__title"><i class="bi bi-moon-stars"></i> Actualizaciones automáticas</span>
                <small class="dd-muted">
                  Cada madrugada (~04:30) el panel actualiza este WordPress con el mismo flujo
                  seguro: checkpoint, verificación y rollback automático si algo se rompe.
                  Si hay un rollback recibirás un aviso en el panel.
                </small>
              </div>
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" role="switch"
                       :checked="safeData.auto_update" :disabled="!!busy"
                       @change="toggleAutoUpdate($event.target.checked)" />
              </div>
            </div>

            <!-- Historial de ejecuciones -->
            <div class="wpm-cli-hist" style="margin-top:1rem">
              <div class="wpm-cli-hist__head">
                <span><i class="bi bi-clock-history"></i> Últimas actualizaciones</span>
                <button class="wpm-mini" @click="loadSafeUpdate" title="Refrescar"><i class="bi bi-arrow-clockwise"></i></button>
              </div>
              <table v-if="safeData.history && safeData.history.length" class="wpm-table">
                <thead><tr><th>Fecha</th><th>Modo</th><th>Actualizado</th><th>Resultado</th></tr></thead>
                <tbody>
                  <tr v-for="h in safeData.history" :key="h.id">
                    <td style="font-size:.78rem;white-space:nowrap">{{ h.started_at ? formatDate(h.started_at) : '—' }}</td>
                    <td style="font-size:.78rem">{{ h.mode === 'auto' ? 'Automático' : 'Manual' }}</td>
                    <td style="font-size:.78rem">{{ safeRunDesc(h) }}</td>
                    <td>
                      <span class="wpm-badge" :class="h.status === 'success' ? 'is-on' : 'is-off'">{{ safeStatusLabel(h.status) }}</span>
                      <small v-if="h.error" class="dd-muted" style="display:block;max-width:22rem">{{ h.error }}</small>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="dd-muted" style="font-size:.82rem;margin:0">Aún no se ha ejecutado ninguna actualización segura en este sitio.</p>
            </div>
          </template>
        </template>
      </div>

      <!-- ── Tab Staging (clonar / push to live) ── -->
      <div v-else-if="tab === 'staging'" class="wpm-pane">
        <div v-if="stagingLoading && !stagingData" class="wpm-loading"><span class="spinner"></span> Consultando el staging…</div>
        <template v-else-if="stagingData">
          <!-- Operación en curso -->
          <div v-if="stagingJob && stagingJob.status === 'running'" class="wpm-stgjob">
            <p class="wpm-stgjob__title"><span class="spinner"></span>
              {{ stagingJob.op === 'create' ? 'Creando el entorno de staging…' : stagingJob.op === 'push' ? 'Volcando el staging a producción…' : 'Eliminando el staging…' }}
            </p>
            <ul class="wpm-stgsteps">
              <li v-for="(s, i) in stagingJob.steps" :key="i"
                  :class="{ 'is-done': i < stagingJob.current, 'is-current': i === stagingJob.current }">
                <i class="bi" :class="i < stagingJob.current ? 'bi-check-circle-fill' : (i === stagingJob.current ? 'bi-arrow-repeat' : 'bi-circle')"></i>
                {{ s }}
              </li>
            </ul>
            <small class="dd-muted">Puede tardar varios minutos en sitios grandes. Puedes salir de esta página: la operación sigue en el servidor.</small>
          </div>

          <template v-else>
            <div v-if="stagingJob && stagingJob.status === 'failed'" class="wpm-stgfail">
              <i class="bi bi-exclamation-triangle"></i> La última operación de staging falló: {{ stagingJob.error }}
            </div>

            <!-- Sin staging: explicación + crear -->
            <div v-if="!stagingData.exists" class="wpm-stgempty">
              <p class="wpm-sec__title"><i class="bi bi-layers"></i> Entorno de staging</p>
              <p class="dd-muted" style="margin:.25rem 0 .9rem; line-height:1.5">
                Crea una copia exacta de este WordPress en <code>{{ stagingData.staging_name }}</code>
                para probar cambios (plugins, temas, actualizaciones) sin tocar el sitio real.
                Cuando todo funcione, vuelca los cambios a producción con un clic (con copia de
                seguridad previa del live). El staging no se indexa en buscadores.
              </p>
              <BaseButton variant="primary" icon="layers" :loading="busy==='stg-create'" :disabled="!!busy" @click="stagingOp('create')">Crear staging</BaseButton>
            </div>

            <!-- Staging existente -->
            <template v-else>
              <div class="wpm-summary" style="margin-bottom:.25rem">
                <div class="wpm-stat">
                  <span class="wpm-stat__k">Staging activo</span>
                  <span class="wpm-stat__v mono"><a :href="stagingData.staging.url" target="_blank" rel="noopener">{{ stagingData.staging.domain_name }}</a></span>
                </div>
                <div class="wpm-stat">
                  <span class="wpm-stat__k">Creado</span>
                  <span class="wpm-stat__v">{{ stagingData.staging.created_at ? formatDate(stagingData.staging.created_at) : '—' }}</span>
                </div>
                <div class="wpm-stat">
                  <span class="wpm-stat__k">SSL</span>
                  <span class="wpm-stat__v">{{ stagingData.staging.ssl_enabled ? 'Activo' : 'HTTP (actívalo en su ficha de dominio)' }}</span>
                </div>
              </div>
              <div class="wpm-actions" style="margin-top:.75rem">
                <a class="wpm-link" :href="stagingData.staging.url" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right"></i> Abrir staging</a>
                <BaseButton variant="primary" size="sm" icon="rocket-takeoff" :loading="busy==='stg-push'" :disabled="!!busy" @click="stagingOp('push')">Volcar a producción</BaseButton>
                <BaseButton variant="danger" size="sm" icon="trash" :loading="busy==='stg-delete'" :disabled="!!busy" @click="stagingOp('delete')">Eliminar staging</BaseButton>
              </div>
              <p class="dd-muted" style="font-size:.82rem;margin-top:.75rem;line-height:1.5">
                <i class="bi bi-info-circle"></i> «Volcar a producción» sobrescribe los archivos y la
                base de datos del sitio live con los del staging (antes se guarda una copia de seguridad
                del live en el servidor). El staging aparece también en tu lista de dominios como un
                subdominio más.
              </p>
            </template>
          </template>
        </template>
      </div>

      <!-- ── Tab Consola WP-CLI ── -->
      <div v-else-if="tab === 'cli'" class="wpm-pane">
        <p class="dd-muted" style="margin:0 0 .75rem">
          Ejecuta comandos <a href="https://developer.wordpress.org/cli/commands/" target="_blank"
          rel="noopener">wp-cli</a> sobre este WordPress, como el usuario del dominio.
          No hace falta escribir el <code>wp</code> inicial.
        </p>

        <div class="wpm-cli-bar">
          <select class="svq-input" style="max-width:16rem" v-model="cliQuickSel" @change="applyQuick">
            <option value="">Comandos rápidos…</option>
            <option v-for="q in cliQuick" :key="q.cmd" :value="q.cmd">{{ q.label }}</option>
          </select>
        </div>

        <div class="wpm-cli-inputrow">
          <span class="wpm-cli-prompt mono">wp</span>
          <input class="svq-input mono" v-model="cliInput" :disabled="cliRunning"
                 placeholder="plugin list --status=active"
                 @keyup.enter="runCli" @keyup.up="cliHistPrev" @keyup.down="cliHistNext" />
          <BaseButton variant="primary" size="sm" icon="play-fill" :loading="cliRunning" @click="runCli">
            Ejecutar
          </BaseButton>
        </div>

        <div v-if="cliLog.length" class="wpm-cli-out mono" ref="cliOutEl">
          <div v-for="(e, i) in cliLog" :key="i" class="wpm-cli-entry">
            <div class="wpm-cli-cmd">$ {{ e.command }}
              <span class="wpm-cli-rc" :class="e.rc === 0 ? 'is-ok' : 'is-err'">rc={{ e.rc }}</span>
            </div>
            <pre v-if="e.stdout" class="wpm-cli-stdout">{{ e.stdout }}</pre>
            <pre v-if="e.stderr" class="wpm-cli-stderr">{{ e.stderr }}</pre>
            <div v-if="e.truncated" class="wpm-cli-stderr">… salida truncada (demasiado larga)</div>
          </div>
        </div>
        <p v-else class="dd-muted" style="margin:.5rem 0 0;font-size:.85em">
          <i class="bi bi-info-circle"></i>
          Ejemplos: <code>plugin list</code> · <code>db optimize</code> ·
          <code>search-replace https://viejo.com https://nuevo.com --dry-run</code> ·
          <code>cron event run --all</code>. Los comandos interactivos
          (<code>shell</code>, <code>db cli</code>) y los flags
          <code>--path/--ssh/--http/--require/--exec</code> están bloqueados.
        </p>

        <!-- Historial persistente (del audit log): sobrevive a recargas -->
        <div class="wpm-cli-hist">
          <div class="wpm-cli-hist__head">
            <span><i class="bi bi-clock-history"></i> Comandos ejecutados (registrados en la auditoría)</span>
            <button class="wpm-mini" @click="loadCliHistory" title="Refrescar"><i class="bi bi-arrow-clockwise"></i></button>
          </div>
          <div v-if="cliHistLoading" class="dd-muted" style="font-size:.82rem"><span class="spinner"></span> Cargando…</div>
          <table v-else-if="cliHistory.length" class="wpm-table">
            <thead><tr><th>Fecha</th><th>Usuario</th><th>Comando</th><th>OK</th><th></th></tr></thead>
            <tbody>
              <tr v-for="h in cliHistory" :key="h.id">
                <td style="font-size:.78rem;white-space:nowrap">{{ formatDate(h.created_at) }}</td>
                <td style="font-size:.78rem">{{ h.user || '—' }}</td>
                <td class="mono" style="font-size:.78rem">{{ h.command || '—' }}</td>
                <td>
                  <i v-if="h.success" class="bi bi-check-circle" style="color:var(--success)"></i>
                  <i v-else class="bi bi-x-circle" style="color:var(--danger)"></i>
                </td>
                <td class="wpm-rowactions">
                  <button v-if="h.command" class="wpm-mini" title="Reutilizar" @click="cliInput = h.command.replace(/^wp /, '')"><i class="bi bi-arrow-return-left"></i></button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="dd-muted" style="font-size:.82rem;margin:0">Aún no se ha ejecutado ningún comando en este sitio.</p>
        </div>
      </div>
    </template>
  </BaseCard>
</template>

<script>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import { formatDateTime } from '../utils/datetime'
import { useMainStore } from '../stores/useMainStore'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseTabs from './ui/BaseTabs.vue'

export default {
  name: 'WpManager',
  components: { BaseCard, BaseButton, BaseTabs },
  props: {
    domainId:   { type: [Number, String], default: null },
    domainName: { type: String, default: '' },
  },
  setup(props) {
    const store = useMainStore()
    const route = useRoute()
    // El id se normaliza a entero válido. Fuente primaria: el prop; respaldo:
    // el parámetro de la ruta (/domains/:id). Así, aunque el prop llegue como
    // NaN/undefined en un render temprano, el componente sigue funcionando.
    const did = computed(() => {
      let n = parseInt(props.domainId, 10)
      if (!Number.isInteger(n)) n = parseInt(route.params.id, 10)
      return Number.isInteger(n) ? n : null
    })
    const info = ref(null)
    const loadingInfo = ref(true)   // arranca en "analizando" hasta la 1ª carga
    const errorInfo = ref('')
    const tab = ref('general')
    const tabs = [
      { key: 'general', label: 'General', icon: 'speedometer2' },
      { key: 'plugins', label: 'Plugins', icon: 'plug' },
      { key: 'themes',  label: 'Temas',   icon: 'palette' },
      { key: 'updates', label: 'Actualizaciones', icon: 'arrow-up-circle' },
      { key: 'access',  label: 'Acceso',  icon: 'key' },
      { key: 'security', label: 'Seguridad', icon: 'shield-check' },
      { key: 'staging', label: 'Staging', icon: 'layers' },
      { key: 'cli',     label: 'Consola', icon: 'terminal' },
    ]
    const busy = ref('')          // id de la acción en curso (desactiva botones)
    const items = ref([])
    const loadingItems = ref(false)
    const admins = ref([])
    const loadingUsers = ref(false)
    const resetResult = ref(null)
    const newUrl = ref('')

    const itemKind = computed(() => (tab.value === 'themes' ? 'theme' : 'plugin'))
    const totalUpdates = computed(() => {
      if (!info.value?.updates) return 0
      const u = info.value.updates
      return (u.core || 0) + (u.plugins || 0) + (u.themes || 0)
    })
    const adminUrl = computed(() => (info.value?.siteurl || '').replace(/\/$/, '') + '/wp-admin')

    const loadingUpdates = ref(false)

    // Carga rápida: una sola llamada wp eval (sin consultar la red por updates).
    const loadInfo = async () => {
      if (did.value == null) { loadingInfo.value = false; return }
      loadingInfo.value = true; errorInfo.value = ''
      try {
        const r = await api.getWpInfo(did.value)
        info.value = r.data
        newUrl.value = r.data.siteurl || ''
        loadUpdates()      // en segundo plano, no bloquea la vista
        loadCronStatus()   // estado del wp-cron (para el botón optimizar)
      } catch (e) { errorInfo.value = e.message || 'No pude leer la instalación' }
      finally { loadingInfo.value = false }
    }

    // Actualizaciones aparte (consulta a wordpress.org, lento): no bloquea.
    const loadUpdates = async () => {
      if (did.value == null) return
      loadingUpdates.value = true
      try {
        const r = await api.getWpUpdates(did.value)
        if (info.value) info.value = { ...info.value, updates: r.data }
      } catch (e) { /* silencioso: el resumen sigue mostrándose sin updates */ }
      finally { loadingUpdates.value = false }
    }

    const loadItems = async () => {
      if (did.value == null) return
      loadingItems.value = true
      try { const r = await api.getWpItems(did.value, itemKind.value); items.value = r.data || [] }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { loadingItems.value = false }
    }

    const loadAdmins = async () => {
      if (did.value == null) return
      loadingUsers.value = true
      try { const r = await api.wpAction(did.value, 'admin-users'); admins.value = r.data.users || [] }
      catch (e) { store.showNotification('Error: ' + e.message, 'danger') }
      finally { loadingUsers.value = false }
    }

    // Ejecuta una acción genérica. Refresca SOLO lo que cambió, sin volver a
    // leer toda la info (cada lectura completa son varios procesos wp-cli).
    const run = async (action, payload, busyId) => {
      if (did.value == null) return
      busy.value = busyId || action
      try {
        const r = await api.wpAction(did.value, action, payload)
        store.showNotification(r.data?.output || r.data?.note || 'Hecho', 'success')
        // Actualización local mínima según la acción:
        if (action === 'maintenance' && info.value) {
          info.value = { ...info.value, maintenance: !!payload.enable }
        } else if (action === 'update-core') {
          await loadInfo()                 // cambia versión/updates: recargar
        } else if (action === 'update-items' || action === 'toggle-item') {
          await loadItems()                // refresca la tabla; updates aparte
          loadUpdates()
        } else if (action === 'delete-item') {
          await loadItems()                // desaparece de la tabla
          loadInfo()                       // actualiza conteos del resumen
        }
        return r.data
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally { busy.value = '' }
    }

    const toggleMaintenance = () => run('maintenance', { enable: !info.value.maintenance }, 'maint')

    const cronOptimized = ref(false)
    const cronLoaded = ref(false)
    const cronBtnLabel = computed(() => {
      if (!cronLoaded.value) return 'Comprobando wp-cron…'
      return cronOptimized.value ? 'wp-cron optimizado (desactivar)' : 'Optimizar wp-cron'
    })
    const loadCronStatus = async () => {
      if (did.value == null) return
      try {
        const r = await api.wpAction(did.value, 'cron-status')
        cronOptimized.value = !!r.data?.optimized
        cronLoaded.value = true
      } catch (e) { /* silencioso */ }
    }
    const toggleCronOptimize = async () => {
      const data = await run('optimize-cron', { enable: !cronOptimized.value }, 'wpcron')
      if (data) cronOptimized.value = !!data.optimized
    }

    const deleteItem = (it) => {
      const tipo = itemKind.value === 'theme' ? 'tema' : 'plugin'
      if (!confirm(`¿Eliminar el ${tipo} "${it.title || it.name}"? Se borrarán sus archivos de forma permanente.`)) return
      run('delete-item', { kind: itemKind.value, name: it.name }, 'd:' + it.name)
    }

    const confirmSalts = () => {
      if (confirm('Regenerar las claves de seguridad cerrará TODAS las sesiones abiertas (tendrás que volver a iniciar sesión). ¿Continuar?'))
        run('regenerate-salts', {}, 'salts')
    }

    const resetPw = async (login) => {
      if (!confirm(`¿Resetear la contraseña de "${login}"? Se generará una nueva.`)) return
      resetResult.value = null
      const data = await run('reset-password', { user_login: login }, 'pw')
      if (data?.new_password) resetResult.value = data
    }

    const changeUrl = () => {
      if (!newUrl.value) return
      if (!confirm(`¿Cambiar la URL del sitio a ${newUrl.value}?`)) return
      run('set-url', { url: newUrl.value }, 'url')
    }

    const statusLabel = (s) => ({ active: 'Activo', inactive: 'Inactivo', 'must-use': 'Must-use', 'dropin': 'Drop-in', parent: 'Padre' }[s] || s)

    // ── Seguridad (anti fuerza bruta WordPress) ──────────────────────────────
    const prot = ref({ xmlrpc_blocked: false, wp_login_ratelimit: 0 })
    const attack = ref(null)
    const rlInput = ref(0)
    const loadingSec = ref(false)

    const loadSecurity = async () => {
      if (did.value == null) return
      loadingSec.value = true
      try {
        // api.get() devuelve el JSON directamente (no envuelto en {data}).
        const r = await api.getDomainWpProtection(did.value)
        prot.value = { xmlrpc_blocked: r.xmlrpc_blocked, wp_login_ratelimit: r.wp_login_ratelimit }
        rlInput.value = r.wp_login_ratelimit || 0
        attack.value = r.attack || null
      } catch (e) { /* silencioso: el pane simplemente no muestra estado */ }
      finally { loadingSec.value = false }
      loadHardening()
    }

    const hardening = ref(null)
    const hardeningLoading = ref(false)
    const loadHardening = async () => {
      if (did.value == null) return
      hardeningLoading.value = true
      try {
        const r = await api.wpAction(did.value, 'hardening-status')
        hardening.value = r.data
      } catch (e) { /* silencioso */ }
      finally { hardeningLoading.value = false }
    }
    const applyHardening = async () => {
      const data = await run('hardening-apply', {}, 'harden')
      if (data) hardening.value = data
    }

    const applyProtection = async (body, busyId) => {
      busy.value = busyId
      try {
        const r = await api.setDomainWpProtection(did.value, body)
        prot.value = { xmlrpc_blocked: r.xmlrpc_blocked, wp_login_ratelimit: r.wp_login_ratelimit }
        rlInput.value = r.wp_login_ratelimit || 0
        // tras aplicar, el aviso de ataque deja de tener sentido para lo mitigado
        await loadSecurity()
        store.showNotification('Protección actualizada', 'success')
      } catch (e) {
        store.showNotification('Error: ' + (e.message || 'no se pudo aplicar'), 'danger')
      } finally { busy.value = '' }
    }

    const toggleXmlrpc = (checked) => applyProtection({ xmlrpc_blocked: checked }, 'wpx')
    const saveRateLimit = () => applyProtection({ wp_login_ratelimit: Math.max(0, Math.min(600, rlInput.value || 0)) }, 'wprl')
    // Botón del aviso: bloquea xmlrpc y pone 3/min en wp-login de una vez.
    const enableAllProtection = () => applyProtection({ xmlrpc_blocked: true, wp_login_ratelimit: 3 }, 'wpprotect-all')

    // ── Staging (clonar / push to live) ──────────────────────────────────────
    const stagingData = ref(null)
    const stagingLoading = ref(false)
    let stagingTimer = null

    const stagingJob = computed(() => stagingData.value?.job || null)

    const stopStagingPoll = () => {
      if (stagingTimer) { clearInterval(stagingTimer); stagingTimer = null }
    }
    // Mientras hay una operación en curso, refresca el estado cada 3 s. Al
    // terminar, notifica el resultado y recarga (aparece/desaparece el staging).
    const startStagingPoll = () => {
      if (stagingTimer) return
      stagingTimer = setInterval(async () => {
        if (did.value == null) return
        try {
          const r = await api.getWpStaging(did.value)
          stagingData.value = r.data
          const st = r.data.job?.status
          if (st && st !== 'running') {
            stopStagingPoll()
            if (st === 'success') store.showNotification('Operación de staging completada', 'success')
            else store.showNotification('Staging: ' + (r.data.job.error || 'la operación falló'), 'danger')
          }
        } catch (e) { /* silencioso: se reintenta en el siguiente tick */ }
      }, 3000)
    }

    const loadStaging = async () => {
      if (did.value == null) return
      stagingLoading.value = true
      try {
        const r = await api.getWpStaging(did.value)
        stagingData.value = r.data
        if (r.data.job?.status === 'running') startStagingPoll()
      } catch (e) { /* silencioso */ }
      finally { stagingLoading.value = false }
    }

    const stagingOp = async (op) => {
      const stgName = stagingData.value?.staging_name || ('staging.' + (props.domainName || ''))
      const msgs = {
        create: `Se creará ${stgName} con una copia completa de los archivos y la base de datos de este sitio. ¿Continuar?`,
        push: 'VOLCAR EL STAGING A PRODUCCIÓN:\n\nLos archivos y la base de datos del sitio LIVE se sobrescribirán con los del staging. Antes se guarda una copia de seguridad del live en el servidor, pero los cambios hechos en producción después de crear el staging (pedidos, comentarios, entradas…) se PERDERÁN.\n\n¿Continuar?',
        delete: '¿Eliminar el entorno de staging? Se borrarán su subdominio, sus archivos y su base de datos. El sitio de producción no se toca.',
      }
      if (!confirm(msgs[op])) return
      busy.value = 'stg-' + op
      try {
        const r = await api.wpStagingOp(did.value, op)
        stagingData.value = { ...(stagingData.value || {}), job: r.data.job }
        startStagingPoll()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally { busy.value = '' }
    }

    onUnmounted(stopStagingPoll)

    // ── Actualización segura (checkpoint + verificación + rollback) ─────────
    const safeData = ref(null)
    const safeLoading = ref(false)
    let safeTimer = null

    const safeJob = computed(() => safeData.value?.job || null)

    const stopSafePoll = () => {
      if (safeTimer) { clearInterval(safeTimer); safeTimer = null }
    }
    const startSafePoll = () => {
      if (safeTimer) return
      safeTimer = setInterval(async () => {
        if (did.value == null) return
        try {
          const r = await api.getWpSafeUpdate(did.value)
          safeData.value = r.data
          const st = r.data.job?.status
          if (st && st !== 'running') {
            stopSafePoll()
            if (st === 'success') {
              store.showNotification('Actualización completada y verificada', 'success')
              loadInfo()   // versión/updates cambiaron
            } else if (r.data.job.rolled_back) {
              store.showNotification('La actualización rompió el sitio: se restauró el punto de recuperación', 'warning')
            } else {
              store.showNotification('Actualización: ' + (r.data.job.error || 'falló'), 'danger')
            }
          }
        } catch (e) { /* silencioso: se reintenta en el siguiente tick */ }
      }, 3000)
    }

    const loadSafeUpdate = async () => {
      if (did.value == null) return
      safeLoading.value = true
      try {
        const r = await api.getWpSafeUpdate(did.value)
        safeData.value = r.data
        if (r.data.job?.status === 'running') startSafePoll()
      } catch (e) { /* silencioso */ }
      finally { safeLoading.value = false }
    }

    const runSafeUpdate = async () => {
      if (!confirm('Se actualizarán el core, los plugins y los temas. Antes se crea un punto de restauración y, si la actualización rompe el sitio, se restaura automáticamente. ¿Continuar?')) return
      busy.value = 'safe-run'
      try {
        const r = await api.wpSafeUpdateRun(did.value)
        safeData.value = { ...(safeData.value || {}), job: r.data.job }
        startSafePoll()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally { busy.value = '' }
    }

    const toggleAutoUpdate = async (checked) => {
      busy.value = 'safe-auto'
      try {
        const r = await api.wpSafeUpdateAuto(did.value, checked)
        safeData.value = { ...(safeData.value || {}), auto_update: r.data.auto_update }
        store.showNotification(r.message || 'Preferencia guardada', 'success')
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
        loadSafeUpdate()   // re-sincroniza el switch con el estado real
      } finally { busy.value = '' }
    }

    const safeStatusLabel = (s) => ({
      success: 'OK', rolled_back: 'Rollback', failed: 'Error', running: 'En curso',
    }[s] || s)

    const safeRunDesc = (h) => {
      const u = h.updated_items
      if (!u) return '—'
      const parts = []
      if (u.core) parts.push('core → ' + u.core)
      if (u.plugins?.length) parts.push(u.plugins.length + ' plugin(s)')
      if (u.themes?.length) parts.push(u.themes.length + ' tema(s)')
      return parts.length ? parts.join(' · ') : 'Nada pendiente'
    }

    onUnmounted(stopSafePoll)

    // ── Consola WP-CLI ──
    const cliInput = ref('')
    const cliRunning = ref(false)
    const cliLog = ref([])        // entradas {command, rc, stdout, stderr, truncated}
    const cliQuickSel = ref('')
    const cliOutEl = ref(null)
    const cliHist = ref([])       // historial de comandos (flechas ↑/↓)
    let cliHistIdx = -1

    const cliQuick = [
      { label: 'Listar plugins activos',        cmd: 'plugin list --status=active' },
      { label: 'Optimizar base de datos',       cmd: 'db optimize' },
      { label: 'Reparar base de datos',         cmd: 'db repair' },
      { label: 'Vaciar transients',             cmd: 'transient delete --all' },
      { label: 'Ejecutar crons pendientes',     cmd: 'cron event run --due-now' },
      { label: 'Comprobar integridad del core', cmd: 'core verify-checksums' },
      { label: 'Buscar y reemplazar (prueba)',  cmd: "search-replace 'https://viejo.com' 'https://nuevo.com' --dry-run" },
      { label: 'Redis Object Cache (requiere su plugin)', cmd: 'redis status' },
    ]

    const applyQuick = () => {
      if (cliQuickSel.value) { cliInput.value = cliQuickSel.value; cliQuickSel.value = '' }
    }

    const cliHistPrev = () => {
      if (!cliHist.value.length) return
      cliHistIdx = cliHistIdx < 0 ? cliHist.value.length - 1 : Math.max(0, cliHistIdx - 1)
      cliInput.value = cliHist.value[cliHistIdx]
    }
    const cliHistNext = () => {
      if (cliHistIdx < 0) return
      cliHistIdx += 1
      if (cliHistIdx >= cliHist.value.length) { cliHistIdx = -1; cliInput.value = ''; return }
      cliInput.value = cliHist.value[cliHistIdx]
    }

    // Historial persistente (audit log): sobrevive a recargas de página.
    const cliHistory = ref([])
    const cliHistLoading = ref(false)
    const loadCliHistory = async () => {
      if (did.value == null) return
      cliHistLoading.value = true
      try { const r = await api.wpCliHistory(did.value); cliHistory.value = r.data || [] }
      catch (e) { /* silencioso: el historial es secundario */ }
      finally { cliHistLoading.value = false }
    }

    const formatDate = formatDateTime

    const runCli = async () => {
      const command = cliInput.value.trim()
      if (!command || cliRunning.value) return
      cliRunning.value = true
      try {
        const r = await api.wpCli(did.value, command)
        cliLog.value.push(r.data)
        cliHist.value.push(command)
        cliHistIdx = -1
        cliInput.value = ''
        await nextTick()
        if (cliOutEl.value) cliOutEl.value.scrollTop = cliOutEl.value.scrollHeight
        loadCliHistory()   // refresca el registro persistente
      } catch (e) {
        store.showNotification('Error: ' + (e.message || 'no se pudo ejecutar'), 'danger')
      } finally { cliRunning.value = false }
    }

    // Cargar listado al entrar en las pestañas de plugins/temas
    watch(tab, (t) => {
      if ((t === 'plugins' || t === 'themes')) loadItems()
      if (t === 'access' && !admins.value.length) loadAdmins()
      if (t === 'security') loadSecurity()
      if (t === 'updates') loadSafeUpdate()
      if (t === 'staging') loadStaging()
      if (t === 'cli') loadCliHistory()
    })

    // Cargar info cuando el componente esté montado y el id sea válido. Si el id
    // se resuelve más tarde (route.params aún no listo), el watch lo reintenta.
    onMounted(loadInfo)
    watch(did, (v, prev) => { if (v != null && prev == null) loadInfo() })

    return {
      info, loadingInfo, errorInfo, tab, tabs, busy, items, loadingItems,
      admins, loadingUsers, loadingUpdates, resetResult, newUrl, itemKind, totalUpdates, adminUrl,
      loadInfo, loadItems, loadAdmins, run, toggleMaintenance, deleteItem, confirmSalts,
      cronOptimized, cronLoaded, cronBtnLabel, toggleCronOptimize,
      resetPw, changeUrl, statusLabel,
      prot, attack, rlInput, loadSecurity, toggleXmlrpc, saveRateLimit, enableAllProtection,
      hardening, hardeningLoading, applyHardening,
      stagingData, stagingLoading, stagingJob, loadStaging, stagingOp,
      safeData, safeLoading, safeJob, loadSafeUpdate, runSafeUpdate,
      toggleAutoUpdate, safeStatusLabel, safeRunDesc,
      cliInput, cliRunning, cliLog, cliQuick, cliQuickSel, cliOutEl,
      runCli, applyQuick, cliHistPrev, cliHistNext,
      cliHistory, cliHistLoading, loadCliHistory, formatDate,
    }
  },
}
</script>

<style scoped>
.wpm-loading, .wpm-error { display:flex; align-items:center; gap:.5rem; padding:.75rem 0; color: var(--text-muted); }
.wpm-error { color: var(--danger); }
.wpm-summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px,1fr)); gap:.5rem; margin-bottom:.75rem; }
.wpm-summary--loading { opacity:.7; }
.wpm-stat { background: var(--surface-inset); border:1px solid var(--border); border-radius: var(--radius-md); padding:.5rem .75rem; }
.wpm-stat__k { display:block; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; color: var(--text-muted); }
.wpm-stat__v { font-weight:600; }
.wpm-updbanner, .wpm-uptodate { display:flex; align-items:center; gap:.5rem; padding:.55rem .75rem; border-radius: var(--radius-md); margin-bottom:.75rem; font-size:.9rem; }
.wpm-updbanner { background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--warning); }
.wpm-uptodate { background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success); }
.wpm-pane { padding-top:.75rem; }
.wpm-actions { display:flex; align-items:center; gap:.75rem; margin-bottom:.75rem; flex-wrap:wrap; }
.wpm-link { display:inline-flex; align-items:center; gap:.3rem; font-size:.85rem; color: var(--accent); text-decoration:none; }
.wpm-link:hover { text-decoration: underline; }
.wpm-quick { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:.5rem; }
.wpm-qbtn { display:flex; align-items:center; gap:.5rem; padding:.6rem .8rem; border:1px solid var(--border); background: var(--surface); border-radius: var(--radius-md); cursor:pointer; color: var(--text); font-size:.88rem; text-align:left; transition: background .15s; }
.wpm-qbtn:hover:not(:disabled) { background: var(--surface-inset); }
.wpm-qbtn:disabled { opacity:.5; cursor:not-allowed; }
.wpm-qbtn--warn { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 40%, var(--border)); }
.wpm-itembar { display:flex; align-items:center; justify-content:space-between; gap:.75rem; margin-bottom:.5rem; }
.wpm-table { width:100%; border-collapse: collapse; font-size:.86rem; }
.wpm-table th { text-align:left; font-size:.72rem; text-transform:uppercase; color: var(--text-muted); padding:.4rem .5rem; border-bottom:1px solid var(--border); }
.wpm-table td { padding:.5rem; border-bottom:1px solid var(--border); vertical-align:top; }
.wpm-name { font-weight:600; }
.wpm-newver { color: var(--warning); font-size:.78rem; }

/* Inputs/selects del componente: .svq-input vive en el scoped de DomainDetail
   y NO alcanza a los hijos; sin esta regla salían con el estilo nativo. */
.wpm-pane .svq-input {
  height: 36px; padding: 0 .65rem;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong, var(--border));
  border-radius: var(--radius-md); font-size: .86rem;
}
.wpm-pane select.svq-input { cursor: pointer; }
.wpm-pane .svq-input:focus {
  outline: none; border-color: var(--color-primary, var(--accent));
  box-shadow: var(--shadow-focus, 0 0 0 3px color-mix(in srgb, var(--accent) 20%, transparent));
}

/* ── Consola WP-CLI ── */
.wpm-cli-bar { margin-bottom:.5rem; }
.wpm-cli-inputrow .svq-input { flex:1; }
.wpm-cli-inputrow { display:flex; align-items:center; gap:.5rem; }
.wpm-cli-prompt { color: var(--text-muted); font-weight:700; }
.wpm-cli-out {
  margin-top:.75rem; max-height: 420px; overflow:auto;
  background: var(--surface-inset); border:1px solid var(--border);
  border-radius: var(--radius-md); padding:.6rem .75rem; font-size:.8rem;
}
.wpm-cli-entry { margin-bottom:.75rem; }
.wpm-cli-entry:last-child { margin-bottom:0; }
.wpm-cli-cmd { font-weight:700; margin-bottom:.2rem; }
.wpm-cli-rc { font-weight:600; font-size:.72rem; margin-left:.5rem; padding:.05rem .4rem; border-radius:999px; }
.wpm-cli-rc.is-ok  { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.wpm-cli-rc.is-err { background: color-mix(in srgb, var(--danger) 15%, transparent);  color: var(--danger); }
.wpm-cli-stdout, .wpm-cli-stderr { margin:0; white-space:pre-wrap; word-break:break-word; font-size:.8rem; }
.wpm-cli-stderr { color: var(--danger); }
.wpm-cli-hist { margin-top:1.25rem; border-top:1px solid var(--border); padding-top:.75rem; }
.wpm-cli-hist__head { display:flex; align-items:center; justify-content:space-between; gap:.5rem; margin-bottom:.5rem; font-size:.82rem; font-weight:600; color: var(--text-muted); }
.wpm-badge { font-size:.72rem; padding:.15rem .5rem; border-radius:999px; }
.wpm-badge.is-on { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.wpm-badge.is-off { background: var(--surface-inset); color: var(--text-muted); }
.wpm-rowactions { white-space:nowrap; text-align:right; }
.wpm-mini { background:none; border:1px solid var(--border); border-radius: var(--radius-sm); width:30px; height:30px; cursor:pointer; color: var(--text); margin-left:.25rem; }
.wpm-mini:hover:not(:disabled) { background: var(--surface-inset); }
.wpm-mini:disabled { opacity:.5; cursor:not-allowed; }
.wpm-mini--danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border)); }
.wpm-mini--danger:hover:not(:disabled) { background: color-mix(in srgb, var(--danger) 12%, transparent); }
.wpm-urlbox { margin-top:1rem; padding-top:1rem; border-top:1px solid var(--border); }
.wpm-urlrow { display:flex; gap:.5rem; align-items:center; }
.wpm-urlrow .svq-input { flex:1; }
.mono { font-family: var(--font-mono, monospace); }

/* ── Pane Seguridad ── */
.wpm-attack { display:flex; gap:.75rem; padding:.85rem 1rem; margin-bottom:1rem;
  border:1px solid color-mix(in srgb, var(--danger) 45%, var(--border));
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-radius: var(--radius-md); }
.wpm-attack__icon { color: var(--danger); font-size:1.4rem; line-height:1; padding-top:.1rem; }
.wpm-attack__body { flex:1; }
.wpm-attack__body strong { color: var(--danger); }
.wpm-attack__body p { margin:.35rem 0 .6rem; font-size:.88rem; color: var(--text); }
.wpm-attack__body code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.82rem; }
.wpm-sec { display:flex; flex-direction:column; gap:.25rem; }
.wpm-sec__row { display:flex; align-items:center; justify-content:space-between; gap:1rem;
  padding:.85rem 0; border-bottom:1px solid var(--border); }
.wpm-sec__row:last-child { border-bottom:none; }
.wpm-sec__info { flex:1; }
.wpm-sec__title { display:flex; align-items:center; gap:.45rem; font-weight:600; margin-bottom:.2rem; }
.wpm-sec__info small { display:block; line-height:1.4; }
.wpm-sec__info code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.8rem; }
.wpm-sec__rl { display:flex; align-items:center; gap:.5rem; white-space:nowrap; }
.wpm-harden { margin-top:1rem; padding-top:1rem; border-top:1px solid var(--border); }
.wpm-harden__head { display:flex; align-items:center; gap:.75rem; margin-bottom:.6rem; }
.wpm-harden__score { font-weight:700; font-size:.8rem; padding:.1rem .5rem; border-radius:999px; background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.wpm-harden__score.is-full { background: color-mix(in srgb, var(--success) 18%, transparent); color: var(--success); }
.wpm-harden__list { list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:.5rem; }
.wpm-harden__list li { display:flex; gap:.6rem; align-items:flex-start; }
.wpm-harden__list li > i { color: var(--warning); font-size:1.05rem; margin-top:.1rem; }
.wpm-harden__list li.is-ok > i { color: var(--success); }
.wpm-harden__label { display:block; font-weight:600; font-size:.9rem; }
.wpm-harden__list small { display:block; line-height:1.35; }
/* ── Pane Staging ── */
.wpm-stgjob__title { display:flex; align-items:center; gap:.5rem; font-weight:600; margin:0 0 .75rem; }
.wpm-stgsteps { list-style:none; padding:0; margin:0 0 .75rem; display:flex; flex-direction:column; gap:.45rem; }
.wpm-stgsteps li { display:flex; align-items:center; gap:.55rem; font-size:.9rem; color: var(--text-muted); }
.wpm-stgsteps li > i { color: var(--text-muted); }
.wpm-stgsteps li.is-done { color: var(--text); }
.wpm-stgsteps li.is-done > i { color: var(--success); }
.wpm-stgsteps li.is-current { color: var(--text); font-weight:600; }
.wpm-stgsteps li.is-current > i { color: var(--accent); animation: wpm-spin 1s linear infinite; }
@keyframes wpm-spin { to { transform: rotate(360deg); } }
.wpm-stgfail { display:flex; align-items:flex-start; gap:.5rem; padding:.6rem .8rem; margin-bottom:.75rem;
  border:1px solid color-mix(in srgb, var(--danger) 40%, var(--border));
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-radius: var(--radius-md); color: var(--danger); font-size:.88rem; }
.wpm-stgempty code { background: var(--surface-inset); padding:.05rem .3rem; border-radius:4px; font-size:.85rem; }

/* toggle basado en clase (no depende de :checked, robusto frente a CSS global) */
.wpm-toggle { position:relative; flex-shrink:0; width:44px; height:24px; padding:0;
  border:1px solid var(--border); border-radius:999px; background: var(--surface-inset);
  cursor:pointer; transition: background .2s, border-color .2s; }
.wpm-toggle__knob { position:absolute; top:2px; left:2px; width:18px; height:18px;
  background:#fff; border-radius:50%; transition: transform .2s; box-shadow:0 1px 2px rgba(0,0,0,.25); }
.wpm-toggle.is-on { background: var(--accent, #6366f1); border-color: var(--accent, #6366f1); }
.wpm-toggle.is-on .wpm-toggle__knob { transform: translateX(20px); }
.wpm-toggle:disabled { opacity:.55; cursor:not-allowed; }
</style>
