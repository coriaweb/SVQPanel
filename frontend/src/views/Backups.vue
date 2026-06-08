<template>
  <div class="sv-view">
    <!-- Cabecera page-head -->
    <div class="page-head">
      <div>
        <h1 class="page-head__title">Copias de seguridad</h1>
        <p class="page-head__sub">{{ jobs.length }} {{ jobs.length === 1 ? 'trabajo de backup' : 'trabajos de backup' }}</p>
      </div>
      <BaseButton variant="primary" size="sm" @click="openCreate">
        <i class="bi bi-plus-circle"></i> Nuevo backup
      </BaseButton>
    </div>

    <!-- Aviso informativo -->
    <div class="bk-info">
      <i class="bi bi-info-circle-fill"></i>
      <div>
        Cada backup respalda lo que selecciones (<strong>web</strong>, <strong>bases de datos</strong> y/o
        <strong>correo</strong>) de un dominio. Las copias <strong>incrementales</strong> solo guardan lo que
        cambió usando enlaces duros, y las bases de datos se comprimen para ocupar poco disco. El destino
        puede ser local (<code>/backups</code>) o un servidor remoto por <strong>SFTP</strong>.
      </div>
    </div>

    <!-- Tabla de jobs -->
    <BaseCard title="Trabajos de backup" icon="hdd-stack" flush>
      <div v-if="loading" class="bk-center"><div class="spinner-border spinner-border-sm"></div></div>

      <EmptyState v-else-if="jobs.length === 0" icon="hdd-stack"
                  title="Sin backups"
                  description="No hay backups configurados todavía. Crea el primero con «Nuevo backup»." />

      <div v-else class="bk-table-wrap">
        <table class="bk-table">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Dominio</th>
              <th>Contenido</th>
              <th>Tipo</th>
              <th>Destino</th>
              <th>Programación</th>
              <th>Última copia</th>
              <th class="bk-right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id" :class="{ 'bk-row--off': !job.is_active }">
              <td>
                <div class="bk-name">{{ job.name }}</div>
                <div v-if="job.description" class="bk-muted">{{ job.description }}</div>
              </td>
              <td class="bk-muted">{{ job.domain_id ? domainName(job.domain_id) : 'Todos' }}</td>
              <td>
                <span v-if="job.include_files" class="bk-tag bk-tag--web" title="Archivos web">Web</span>
                <span v-if="job.include_databases" class="bk-tag bk-tag--db" title="Bases de datos">BD</span>
                <span v-if="job.include_mail" class="bk-tag bk-tag--mail" title="Correo">Correo</span>
              </td>
              <td>
                <span class="bk-tag" :class="job.backup_type === 'incremental' ? 'bk-tag--inc' : 'bk-tag--full'">
                  {{ job.backup_type === 'incremental' ? 'Incremental' : 'Completa' }}
                </span>
              </td>
              <td class="bk-muted">
                <i :class="job.destination_type === 'sftp' ? 'bi bi-hdd-network' : (job.destination_type === 's3' ? 'bi bi-cloud-arrow-up' : 'bi bi-hdd')"></i>
                {{ job.destination_type === 'sftp' ? (job.sftp_host || 'SFTP') : (job.destination_type === 's3' ? (job.s3_bucket || 'S3') : 'Local') }}
              </td>
              <td class="bk-muted">
                <span v-if="job.schedule_enabled" class="bk-sched" :title="cronSummary(job)">
                  <i class="bi bi-clock"></i> {{ cronSummary(job) }}
                </span>
                <span v-else>Manual</span>
              </td>
              <td class="bk-muted">
                <span v-if="runningJobId === job.id" class="bk-running">
                  <span class="spinner-border spinner-border-sm"></span> En curso…
                </span>
                <template v-else-if="job.last_record_status">
                  <span class="bk-status" :class="statusClass(job.last_record_status)">{{ statusLabel(job.last_record_status) }}</span>
                  <div class="bk-muted">
                    {{ formatDate(job.last_run) }}
                    <span v-if="job.last_record_size_mb"> · {{ job.last_record_size_mb }} MB</span>
                  </div>
                </template>
                <span v-else>Nunca</span>
              </td>
              <td class="bk-right">
                <div class="bk-actions">
                  <button class="bk-iconbtn" title="Ejecutar ahora"
                          :disabled="runningJobId === job.id || !job.is_active" @click="runJob(job)">
                    <i class="bi bi-play-fill"></i>
                  </button>
                  <button class="bk-iconbtn" title="Restaurar una copia"
                          :disabled="runningJobId === job.id" @click="openRestore(job)">
                    <i class="bi bi-arrow-counterclockwise"></i>
                  </button>
                  <button class="bk-iconbtn" title="Historial" @click="openHistory(job)">
                    <i class="bi bi-clock-history"></i>
                  </button>
                  <button class="bk-iconbtn" title="Editar" @click="openEdit(job)">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button class="bk-iconbtn bk-iconbtn--danger" title="Eliminar" @click="deleteJob(job)">
                    <i class="bi bi-trash"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <!-- Modal crear/editar -->
    <div v-if="showForm" class="bk-modal" @click.self="closeForm">
      <div class="bk-modal__dialog bk-modal__dialog--xl">
        <div class="bk-modal__head">
          <h5 class="bk-modal__title"><i class="bi bi-archive"></i>{{ editing ? 'Editar backup' : 'Nuevo backup' }}</h5>
          <button type="button" class="bk-modal__close" @click="closeForm"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="bk-modal__body bk-form-grid">

            <!-- Columna izquierda -->
            <div style="display:flex;flex-direction:column;gap:1rem">

              <!-- Básico -->
              <div class="bk-section">
                <div class="bk-section-title">General</div>
                <div class="bk-field">
                  <label>Nombre <span class="text-danger">*</span></label>
                  <input v-model="form.name" class="form-control form-control-sm" placeholder="Ej: Backup diario tienda" />
                </div>
                <div class="bk-field">
                  <label>Dominio</label>
                  <select v-model="form.domain_id" class="form-select form-select-sm" :disabled="editing">
                    <option :value="null">— Todos mis dominios —</option>
                    <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.domain_name }}</option>
                  </select>
                  <span class="bk-hint">Sin selección: respalda todos tus dominios.</span>
                </div>
                <div class="bk-field">
                  <label>Descripción</label>
                  <input v-model="form.description" class="form-control form-control-sm" placeholder="Notas sobre este backup" />
                </div>
              </div>

              <!-- Contenido -->
              <div class="bk-section">
                <div class="bk-section-title">¿Qué respaldar?</div>
                <div style="display:flex;gap:1rem;flex-wrap:wrap">
                  <label class="bk-check">
                    <input type="checkbox" v-model="form.include_files" />
                    <i class="bi bi-folder"></i> Archivos web
                  </label>
                  <label class="bk-check">
                    <input type="checkbox" v-model="form.include_databases" />
                    <i class="bi bi-database"></i> Bases de datos
                  </label>
                  <label class="bk-check">
                    <input type="checkbox" v-model="form.include_mail" />
                    <i class="bi bi-envelope"></i> Correo
                  </label>
                </div>
              </div>

              <!-- Tipo y retención -->
              <div class="bk-section">
                <div class="bk-section-title">Opciones</div>
                <div class="bk-field">
                  <label>Tipo de copia</label>
                  <select v-model="form.backup_type" class="form-select form-select-sm">
                    <option value="incremental">Incremental (solo cambios, recomendado)</option>
                    <option value="full">Completa (todo cada vez)</option>
                  </select>
                </div>
                <div class="bk-field">
                  <label>Copias a conservar</label>
                  <input v-model.number="form.retention_copies" type="number" min="1" max="365" class="form-control form-control-sm" />
                  <span class="bk-hint">Se eliminan las más antiguas (solo destino local).</span>
                </div>
                <label class="bk-check" style="margin-top:.25rem">
                  <input type="checkbox" v-model="form.is_active" />
                  Backup activo
                </label>
              </div>

            </div>

            <!-- Columna derecha -->
            <div style="display:flex;flex-direction:column;gap:1rem">

              <!-- Destino -->
              <div class="bk-section">
                <div class="bk-section-title">Destino</div>
                <div style="display:flex;gap:1.5rem;margin-bottom:.75rem">
                  <label class="bk-check">
                    <input type="radio" value="local" v-model="form.destination_type" />
                    <i class="bi bi-hdd"></i> Local
                  </label>
                  <label class="bk-check">
                    <input type="radio" value="sftp" v-model="form.destination_type" />
                    <i class="bi bi-hdd-network"></i> Remoto (SFTP)
                  </label>
                  <label class="bk-check">
                    <input type="radio" value="s3" v-model="form.destination_type" />
                    <i class="bi bi-cloud-arrow-up"></i> S3 / Backblaze
                  </label>
                </div>

                <div v-if="form.destination_type === 'local'" class="bk-field">
                  <label>Ruta local</label>
                  <input v-model="form.local_path" class="form-control form-control-sm font-monospace" placeholder="/backups" />
                </div>

                <!-- S3 / compatible -->
                <div v-else-if="form.destination_type === 's3'" style="display:flex;flex-direction:column;gap:.75rem">
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Bucket <span class="text-danger">*</span></label>
                      <input v-model="form.s3_bucket" class="form-control form-control-sm" placeholder="mis-backups" />
                    </div>
                    <div class="bk-field">
                      <label>Carpeta (prefijo)</label>
                      <input v-model="form.s3_prefix" class="form-control form-control-sm font-monospace" placeholder="svqpanel/" />
                    </div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Endpoint <span class="bk-hint">(vacío = AWS)</span></label>
                      <input v-model="form.s3_endpoint" class="form-control form-control-sm" placeholder="s3.us-west-002.backblazeb2.com" />
                    </div>
                    <div class="bk-field">
                      <label>Región</label>
                      <input v-model="form.s3_region" class="form-control form-control-sm" placeholder="us-west-002 / eu-west-1" />
                    </div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Access Key <span class="text-danger">*</span></label>
                      <input v-model="form.s3_access_key" class="form-control form-control-sm font-monospace" placeholder="AKIA… / keyID" />
                    </div>
                    <div class="bk-field">
                      <label>Secret Key</label>
                      <input v-model="form.s3_secret_key" type="password" class="form-control form-control-sm"
                             :placeholder="editing ? 'Sin cambios' : ''" />
                    </div>
                  </div>
                  <p class="bk-hint" style="margin:0">
                    Compatible con AWS S3, Backblaze B2, Wasabi, MinIO… El backup se sube comprimido (.tar.gz). La retención también se aplica en el bucket.
                  </p>
                  <div v-if="editing" style="display:flex;align-items:center;gap:.75rem">
                    <button class="btn btn-sm btn-outline-info" :disabled="testingS3" @click="testS3">
                      <span v-if="testingS3" class="spinner-border spinner-border-sm me-1"></span>
                      <i v-else class="bi bi-plug"></i> Probar conexión
                    </button>
                    <span v-if="s3TestMsg" :class="s3TestOk ? 'text-success' : 'text-danger'" style="font-size:.82rem">
                      {{ s3TestMsg }}
                    </span>
                  </div>
                </div>

                <!-- SFTP -->
                <div v-else style="display:flex;flex-direction:column;gap:.75rem">
                  <div style="display:grid;grid-template-columns:1fr auto;gap:.5rem">
                    <div class="bk-field">
                      <label>Host SFTP <span class="text-danger">*</span></label>
                      <input v-model="form.sftp_host" class="form-control form-control-sm" placeholder="backup.midominio.com" />
                    </div>
                    <div class="bk-field" style="width:80px">
                      <label>Puerto</label>
                      <input v-model.number="form.sftp_port" type="number" class="form-control form-control-sm" placeholder="22" />
                    </div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Usuario <span class="text-danger">*</span></label>
                      <input v-model="form.sftp_user" class="form-control form-control-sm" placeholder="backupuser" />
                    </div>
                    <div class="bk-field">
                      <label>Contraseña</label>
                      <input v-model="form.sftp_password" type="password" class="form-control form-control-sm"
                             :placeholder="editing ? 'Sin cambios' : 'Opcional'" />
                    </div>
                  </div>
                  <div class="bk-field">
                    <label>Ruta remota</label>
                    <input v-model="form.sftp_path" class="form-control form-control-sm font-monospace" placeholder="/backups" />
                  </div>
                  <div class="bk-field">
                    <label>Clave SSH privada (ruta en servidor)</label>
                    <input v-model="form.sftp_key_path" class="form-control form-control-sm font-monospace" placeholder="/root/.ssh/id_backup" />
                  </div>
                  <div v-if="editing" style="display:flex;align-items:center;gap:.75rem">
                    <button class="btn btn-sm btn-outline-info" :disabled="testingSftp" @click="testSftp">
                      <span v-if="testingSftp" class="spinner-border spinner-border-sm me-1"></span>
                      <i v-else class="bi bi-plug"></i> Probar conexión
                    </button>
                    <span v-if="sftpTestMsg" :class="sftpTestOk ? 'text-success' : 'text-danger'" style="font-size:.82rem">
                      {{ sftpTestMsg }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- Programación -->
              <div class="bk-section">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem">
                  <div class="bk-section-title" style="margin-bottom:0">Programación automática</div>
                  <label class="form-check form-switch mb-0">
                    <input class="form-check-input" type="checkbox" v-model="form.schedule_enabled" style="cursor:pointer" />
                  </label>
                </div>

                <div v-if="form.schedule_enabled">
                  <div style="display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.75rem">
                    <button type="button" class="btn btn-sm" v-for="p in ['daily','weekly','monthly','custom']" :key="p"
                            :class="schedPreset === p ? 'btn-primary' : 'btn-outline-secondary'"
                            @click="p === 'custom' ? schedPreset = 'custom' : applyPreset(p)">
                      {{ p === 'daily' ? 'Diario' : p === 'weekly' ? 'Semanal' : p === 'monthly' ? 'Mensual' : 'Personalizado' }}
                    </button>
                  </div>

                  <div v-if="schedPreset !== 'custom'" style="display:flex;align-items:center;gap:.75rem">
                    <div class="bk-field" style="flex:0">
                      <label>Hora</label>
                      <select v-model="presetHour" class="form-select form-select-sm" style="width:90px" @change="applyPreset(schedPreset)">
                        <option v-for="h in 24" :key="h-1" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00</option>
                      </select>
                    </div>
                    <span style="font-size:.8rem;color:var(--text-muted);padding-top:1.4rem">{{ schedSummary }}</span>
                  </div>

                  <div v-if="schedPreset === 'custom'" style="display:grid;grid-template-columns:repeat(4,1fr);gap:.4rem">
                    <div class="bk-field">
                      <label>Minuto</label>
                      <input v-model="form.schedule_minute" class="form-control form-control-sm font-monospace" placeholder="0" />
                    </div>
                    <div class="bk-field">
                      <label>Hora</label>
                      <input v-model="form.schedule_hour" class="form-control form-control-sm font-monospace" placeholder="2" />
                    </div>
                    <div class="bk-field">
                      <label>Día mes</label>
                      <input v-model="form.schedule_day" class="form-control form-control-sm font-monospace" placeholder="*" />
                    </div>
                    <div class="bk-field">
                      <label>Día semana</label>
                      <input v-model="form.schedule_weekday" class="form-control form-control-sm font-monospace" placeholder="*" />
                    </div>
                    <div style="grid-column:1/-1;font-size:.78rem;color:var(--text-muted);font-family:var(--font-mono)">
                      {{ form.schedule_minute }} {{ form.schedule_hour }} * * {{ form.schedule_weekday }} — {{ schedSummary }}
                    </div>
                  </div>
                </div>
                <p v-else style="font-size:.82rem;color:var(--text-muted);margin:0">Ejecución manual únicamente.</p>
              </div>

            </div>

          <!-- Error a ancho completo -->
          <div v-if="formError" class="bk-alert-error" style="grid-column:1/-1">{{ formError }}</div>

        </div>
        <div class="bk-modal__foot">
          <BaseButton variant="ghost" size="sm" @click="closeForm">Cancelar</BaseButton>
          <BaseButton variant="primary" size="sm" :loading="saving" @click="submitForm">
            {{ editing ? 'Guardar cambios' : 'Crear backup' }}
          </BaseButton>
        </div>
      </div>
    </div>

    <!-- Modal historial -->
    <div v-if="showHistory" class="bk-modal" @click.self="showHistory = false">
      <div class="bk-modal__dialog bk-modal__dialog--lg">
        <div class="bk-modal__head">
          <h5 class="bk-modal__title"><i class="bi bi-clock-history"></i>Historial · {{ historyJob?.name }}</h5>
          <button type="button" class="bk-modal__close" @click="showHistory = false"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="bk-modal__body">
          <div v-if="historyLoading" class="bk-center"><div class="spinner-border spinner-border-sm"></div></div>
          <EmptyState v-else-if="records.length === 0" icon="clock-history"
                      title="Sin ejecuciones" description="Este backup no se ha ejecutado todavía." />
          <div v-else class="bk-table-wrap">
            <table class="bk-table bk-table--sm">
              <thead>
                <tr>
                  <th>Op.</th><th>Fecha</th><th>Estado</th><th>Tipo</th>
                  <th>Tamaño</th><th>Archivos</th><th>BD</th><th>Duración</th><th></th>
                </tr>
              </thead>
              <tbody>
                <template v-for="r in records" :key="r.id">
                  <tr>
                    <td>
                      <span class="bk-tag" :class="r.kind === 'restore' ? 'bk-tag--full' : 'bk-tag--web'">
                        {{ r.kind === 'restore' ? 'Restaurar' : 'Copia' }}
                      </span>
                    </td>
                    <td class="bk-muted">{{ formatDateTime(r.started_at) }}</td>
                    <td><span class="bk-status" :class="statusClass(r.status)">{{ statusLabel(r.status) }}</span></td>
                    <td class="bk-muted">{{ r.is_incremental ? 'Incremental' : 'Completa' }}</td>
                    <td class="bk-muted">{{ r.size_mb }} MB</td>
                    <td class="bk-muted">{{ r.files_transferred }}/{{ r.files_total }}</td>
                    <td class="bk-muted">{{ r.db_count }}</td>
                    <td class="bk-muted">{{ r.duration_seconds != null ? r.duration_seconds + 's' : '—' }}</td>
                    <td>
                      <button v-if="r.log_output || r.error_message" class="bk-iconbtn"
                              @click="expanded === r.id ? expanded = null : expanded = r.id">
                        <i class="bi bi-card-text"></i>
                      </button>
                    </td>
                  </tr>
                  <tr v-if="expanded === r.id" :key="'exp-' + r.id">
                    <td colspan="9" class="bk-logcell">
                      <div v-if="r.error_message" class="bk-logerr">{{ r.error_message }}</div>
                      <pre class="bk-log">{{ r.log_output || 'Sin log' }}</pre>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
        <div class="bk-modal__foot">
          <BaseButton variant="ghost" size="sm" @click="showHistory = false">Cerrar</BaseButton>
        </div>
      </div>
    </div>

    <!-- Modal restaurar -->
    <div v-if="showRestore" class="bk-modal" @click.self="showRestore = false">
      <div class="bk-modal__dialog bk-modal__dialog--lg">
        <div class="bk-modal__head">
          <h5 class="bk-modal__title"><i class="bi bi-arrow-counterclockwise"></i>Restaurar · {{ restoreJob?.name }}</h5>
          <button type="button" class="bk-modal__close" @click="showRestore = false"><i class="bi bi-x-lg"></i></button>
        </div>
        <div class="bk-modal__body">
          <div class="bk-warn">
            <i class="bi bi-exclamation-triangle-fill"></i>
            <div>
              La restauración <strong>sobrescribe</strong> los archivos y tablas con los de la copia
              elegida. No borra archivos creados después de esa copia (se superpone). Elige qué
              restaurar y la copia de origen.
            </div>
          </div>

          <label class="bk-sublabel">¿Qué restaurar?</label>
          <div class="bk-restore-opts">
            <label class="bk-check"><input type="checkbox" v-model="restoreOpts.files" /><i class="bi bi-folder"></i> Archivos web</label>
            <label class="bk-check"><input type="checkbox" v-model="restoreOpts.databases" /><i class="bi bi-database"></i> Bases de datos</label>
            <label class="bk-check"><input type="checkbox" v-model="restoreOpts.mail" /><i class="bi bi-envelope"></i> Correo</label>
          </div>

          <div v-if="snapshotsLoading" class="bk-center"><div class="spinner-border spinner-border-sm"></div></div>
          <EmptyState v-else-if="snapshots.length === 0" icon="hdd"
                      title="Sin copias" description="No hay copias guardadas en disco para este dominio." />
          <div v-else class="bk-table-wrap">
            <table class="bk-table bk-table--sm">
              <thead>
                <tr><th>Copia (fecha)</th><th>Contenido</th><th>Tamaño</th><th>Tipo</th><th class="bk-right"></th></tr>
              </thead>
              <tbody>
                <tr v-for="s in snapshots" :key="s.name">
                  <td class="bk-muted">{{ formatSnapshot(s.name) }}</td>
                  <td>
                    <span v-if="s.has_files" class="bk-tag bk-tag--web">Web</span>
                    <span v-if="s.has_databases" class="bk-tag bk-tag--db">BD</span>
                    <span v-if="s.has_mail" class="bk-tag bk-tag--mail">Correo</span>
                  </td>
                  <td class="bk-muted">{{ s.size_mb }} MB</td>
                  <td class="bk-muted">{{ s.is_incremental ? 'Incremental' : 'Completa' }}</td>
                  <td class="bk-right">
                    <BaseButton variant="primary" size="sm" :loading="restoringSnap === s.name" @click="doRestore(s)">
                      <i class="bi bi-arrow-counterclockwise"></i> Restaurar
                    </BaseButton>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="bk-modal__foot">
          <BaseButton variant="ghost" size="sm" @click="showRestore = false">Cerrar</BaseButton>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, watch, onMounted } from 'vue'
import api from '../services/api.js'
import { useMainStore } from '../stores/useMainStore.js'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import EmptyState from '../components/ui/EmptyState.vue'

function emptyForm() {
  return {
    name: '',
    description: '',
    domain_id: null,
    include_files: true,
    include_databases: true,
    include_mail: false,
    backup_type: 'incremental',
    destination_type: 'local',
    local_path: '/backups',
    sftp_host: '',
    sftp_port: 22,
    sftp_user: '',
    sftp_password: '',
    sftp_path: '/backups',
    sftp_key_path: '',
    s3_endpoint: '',
    s3_region: '',
    s3_bucket: '',
    s3_prefix: '',
    s3_access_key: '',
    s3_secret_key: '',
    retention_copies: 7,
    schedule_enabled: false,
    schedule_minute: '0',
    schedule_hour: '2',
    schedule_day: '*',
    schedule_weekday: '*',
    is_active: true,
  }
}

export default {
  name: 'Backups',
  components: { BaseCard, BaseButton, EmptyState },
  setup() {
    const store = useMainStore()
    const jobs = ref([])
    const domains = ref([])
    const loading = ref(false)

    const showForm = ref(false)
    const editing = ref(null)
    const form = ref(emptyForm())
    const formError = ref('')
    const saving = ref(false)

    const testingSftp = ref(false)
    const sftpTestMsg = ref('')
    const sftpTestOk = ref(false)
    const testingS3 = ref(false)
    const s3TestMsg = ref('')
    const s3TestOk = ref(false)

    const runningJobId = ref(null)

    const showHistory = ref(false)
    const historyJob = ref(null)
    const records = ref([])
    const historyLoading = ref(false)
    const expanded = ref(null)

    const showRestore = ref(false)
    const restoreJob = ref(null)
    const snapshots = ref([])
    const snapshotsLoading = ref(false)
    const restoreOpts = ref({ files: true, databases: true, mail: false })
    const restoringSnap = ref(null)

    const domainName = (id) => {
      const d = domains.value.find(x => x.id === id)
      return d ? d.domain_name : '—'
    }

    const statusLabel = (s) => ({
      pending: 'Pendiente', running: 'En curso', success: 'Correcto',
      failed: 'Fallido', cancelled: 'Cancelado',
    }[s] || s)

    const statusClass = (s) => ({
      success: 'bk-status--ok', failed: 'bk-status--err', running: 'bk-status--run',
      pending: 'bk-status--idle', cancelled: 'bk-status--idle',
    }[s] || 'bk-status--idle')

    const loadJobs = async () => {
      loading.value = true
      try {
        jobs.value = await api.getBackupJobs()
      } catch (e) {
        store.showNotification('Error cargando backups: ' + e.message, 'danger')
      } finally {
        loading.value = false
      }
    }

    const loadDomains = async () => {
      try {
        domains.value = await api.getDomains() || []
      } catch (e) {
        domains.value = []
      }
    }

    const openCreate = () => {
      editing.value = null
      form.value = emptyForm()
      formError.value = ''
      sftpTestMsg.value = ''
      showForm.value = true
    }

    const openEdit = (job) => {
      editing.value = job
      form.value = {
        name: job.name,
        description: job.description || '',
        domain_id: job.domain_id,
        include_files: job.include_files,
        include_databases: job.include_databases,
        include_mail: job.include_mail,
        backup_type: job.backup_type,
        destination_type: job.destination_type,
        local_path: job.local_path || '/backups',
        sftp_host: job.sftp_host || '',
        sftp_port: job.sftp_port || 22,
        sftp_user: job.sftp_user || '',
        sftp_password: '',
        sftp_path: job.sftp_path || '/backups',
        sftp_key_path: job.sftp_key_path || '',
        s3_endpoint: job.s3_endpoint || '',
        s3_region: job.s3_region || '',
        s3_bucket: job.s3_bucket || '',
        s3_prefix: job.s3_prefix || '',
        s3_access_key: job.s3_access_key || '',
        s3_secret_key: '',
        retention_copies: job.retention_copies,
        schedule_enabled: job.schedule_enabled || false,
        schedule_minute:  job.schedule_minute  || '0',
        schedule_hour:    job.schedule_hour    || '2',
        schedule_day:     job.schedule_day     || '*',
        schedule_weekday: job.schedule_weekday || '*',
        is_active: job.is_active,
      }
      schedPreset.value = detectPreset(form.value)
      formError.value = ''
      sftpTestMsg.value = ''
      s3TestMsg.value = ''
      showForm.value = true
    }

    const closeForm = () => { showForm.value = false }

    const submitForm = async () => {
      formError.value = ''
      if (!form.value.name.trim()) { formError.value = 'El nombre es obligatorio.'; return }
      if (!form.value.include_files && !form.value.include_databases && !form.value.include_mail) {
        formError.value = 'Selecciona al menos un contenido a respaldar.'; return
      }
      if (form.value.destination_type === 'sftp' && (!form.value.sftp_host || !form.value.sftp_user)) {
        formError.value = 'Host y usuario SFTP son obligatorios para destino remoto.'; return
      }
      if (form.value.destination_type === 's3' && (!form.value.s3_bucket || !form.value.s3_access_key)) {
        formError.value = 'Bucket y Access Key son obligatorios para destino S3.'; return
      }
      saving.value = true
      try {
        if (editing.value) {
          await api.updateBackupJob(editing.value.id, form.value)
          store.showNotification('Backup actualizado', 'success')
        } else {
          await api.createBackupJob(form.value)
          store.showNotification('Backup creado', 'success')
        }
        showForm.value = false
        await loadJobs()
      } catch (e) {
        formError.value = e.message
      } finally {
        saving.value = false
      }
    }

    const testSftp = async () => {
      if (!editing.value) return
      testingSftp.value = true
      sftpTestMsg.value = ''
      try {
        const res = await api.testBackupSftp(editing.value.id)
        sftpTestOk.value = res.ok
        sftpTestMsg.value = res.message
      } catch (e) {
        sftpTestOk.value = false
        sftpTestMsg.value = e.message
      } finally {
        testingSftp.value = false
      }
    }

    const testS3 = async () => {
      if (!editing.value) return
      testingS3.value = true
      s3TestMsg.value = ''
      try {
        const res = await api.testBackupS3(editing.value.id)
        s3TestOk.value = res.ok
        s3TestMsg.value = res.message
      } catch (e) {
        s3TestOk.value = false
        s3TestMsg.value = e.message
      } finally {
        testingS3.value = false
      }
    }

    const pollRecord = async (recordId) => {
      const FINAL = ['success', 'failed', 'cancelled']
      for (let i = 0; i < 600; i++) {   // hasta ~20 min (2s * 600)
        await new Promise(r => setTimeout(r, 2000))
        let rec
        try {
          rec = await api.getBackupRecord(recordId)
        } catch (e) {
          break
        }
        if (FINAL.includes(rec.status)) return rec
      }
      return null
    }

    const runJob = async (job) => {
      runningJobId.value = job.id
      try {
        const rec = await api.runBackupJob(job.id)
        store.showNotification('Backup iniciado…', 'info')
        const final = await pollRecord(rec.id)
        if (final && final.status === 'success') {
          store.showNotification(`Backup "${job.name}" completado (${final.size_mb} MB)`, 'success')
        } else if (final && final.status === 'failed') {
          store.showNotification(`Backup "${job.name}" falló: ${final.error_message || 'error desconocido'}`, 'danger')
        } else {
          store.showNotification('El backup sigue en curso; revisa el historial.', 'warning')
        }
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        runningJobId.value = null
        await loadJobs()
      }
    }

    const openHistory = async (job) => {
      historyJob.value = job
      showHistory.value = true
      expanded.value = null
      historyLoading.value = true
      try {
        records.value = await api.getBackupRecords(job.id)
      } catch (e) {
        store.showNotification('Error cargando historial: ' + e.message, 'danger')
        records.value = []
      } finally {
        historyLoading.value = false
      }
    }

    const openRestore = async (job) => {
      restoreJob.value = job
      restoreOpts.value = {
        files: job.include_files,
        databases: job.include_databases,
        mail: job.include_mail,
      }
      showRestore.value = true
      snapshotsLoading.value = true
      snapshots.value = []
      try {
        snapshots.value = await api.getBackupSnapshots(job.id)
      } catch (e) {
        store.showNotification('Error cargando copias: ' + e.message, 'danger')
      } finally {
        snapshotsLoading.value = false
      }
    }

    const doRestore = async (snap) => {
      if (!restoreOpts.value.files && !restoreOpts.value.databases && !restoreOpts.value.mail) {
        store.showNotification('Selecciona al menos un contenido a restaurar', 'warning')
        return
      }
      const parts = []
      if (restoreOpts.value.files) parts.push('archivos')
      if (restoreOpts.value.databases) parts.push('bases de datos')
      if (restoreOpts.value.mail) parts.push('correo')
      if (!confirm(`¿Restaurar ${parts.join(', ')} desde la copia del ${formatSnapshot(snap.name)}?\nLos datos actuales serán sobrescritos.`)) return

      restoringSnap.value = snap.name
      try {
        const rec = await api.restoreBackup(restoreJob.value.id, {
          snapshot_name: snap.name,
          restore_files: restoreOpts.value.files,
          restore_databases: restoreOpts.value.databases,
          restore_mail: restoreOpts.value.mail,
        })
        store.showNotification('Restauración iniciada…', 'info')
        const final = await pollRecord(rec.id)
        if (final && final.status === 'success') {
          store.showNotification('Restauración completada', 'success')
          showRestore.value = false
        } else if (final && final.status === 'failed') {
          store.showNotification('Restauración fallida: ' + (final.error_message || 'error'), 'danger')
        } else {
          store.showNotification('La restauración sigue en curso; revisa el historial.', 'warning')
        }
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      } finally {
        restoringSnap.value = null
      }
    }

    const formatSnapshot = (name) => {
      // name = YYYYMMDD_HHMMSS
      const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(name)
      if (!m) return name
      const [, y, mo, d, h, mi] = m
      return `${d}/${mo}/${y} ${h}:${mi}`
    }

    const deleteJob = async (job) => {
      if (!confirm(`¿Eliminar el backup "${job.name}"? No se borran las copias ya guardadas en disco.`)) return
      try {
        await api.deleteBackupJob(job.id)
        store.showNotification('Backup eliminado', 'success')
        await loadJobs()
      } catch (e) {
        store.showNotification('Error: ' + e.message, 'danger')
      }
    }

    // ── Lógica de programación (presets + cron summary) ──────────────────────
    const schedPreset = ref('daily')
    const presetHour  = ref(2)

    const applyPreset = (preset) => {
      schedPreset.value = preset
      form.value.schedule_minute = '0'
      form.value.schedule_hour   = String(presetHour.value)
      form.value.schedule_day    = '*'
      if (preset === 'daily')   { form.value.schedule_weekday = '*' }
      if (preset === 'weekly')  { form.value.schedule_weekday = '0' }
      if (preset === 'monthly') { form.value.schedule_day = '1'; form.value.schedule_weekday = '*' }
    }

    // Detecta qué preset coincide con los valores del form al abrir edición
    const detectPreset = (job) => {
      if (job.schedule_minute === '0' && job.schedule_day === '*' && job.schedule_weekday === '*') {
        presetHour.value = parseInt(job.schedule_hour) || 2
        return 'daily'
      }
      if (job.schedule_minute === '0' && job.schedule_day === '*' && job.schedule_weekday === '0') {
        presetHour.value = parseInt(job.schedule_hour) || 2
        return 'weekly'
      }
      if (job.schedule_minute === '0' && job.schedule_day === '1' && job.schedule_weekday === '*') {
        presetHour.value = parseInt(job.schedule_hour) || 2
        return 'monthly'
      }
      return 'custom'
    }

    const schedSummary = ref('')
    const updateSchedSummary = () => {
      const h = String(presetHour.value).padStart(2, '0')
      if (schedPreset.value === 'daily')        schedSummary.value = `Todos los días a las ${h}:00`
      else if (schedPreset.value === 'weekly')  schedSummary.value = `Cada lunes a las ${h}:00`
      else if (schedPreset.value === 'monthly') schedSummary.value = `El día 1 de cada mes a las ${h}:00`
      else schedSummary.value = `${form.value.schedule_minute} ${form.value.schedule_hour} ${form.value.schedule_day} * ${form.value.schedule_weekday}`
    }
    watch([schedPreset, presetHour, () => form.value.schedule_minute, () => form.value.schedule_hour,
           () => form.value.schedule_day, () => form.value.schedule_weekday], updateSchedSummary, { immediate: true })

    // Resumen legible para la tabla (desde las propiedades del job)
    const cronSummary = (job) => {
      const h = String(job.schedule_hour || '2').padStart(2, '0')
      if (job.schedule_minute === '0' && job.schedule_day === '*' && job.schedule_weekday === '*')
        return `Diario ${h}:00`
      if (job.schedule_minute === '0' && job.schedule_day === '*' && job.schedule_weekday === '0')
        return `Lunes ${h}:00`
      if (job.schedule_minute === '0' && job.schedule_day === '1' && job.schedule_weekday === '*')
        return `Mensual ${h}:00`
      return `${job.schedule_minute} ${job.schedule_hour} ${job.schedule_day} * ${job.schedule_weekday}`
    }

    const formatDate = (dt) => {
      if (!dt) return '—'
      return new Date(dt).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    }
    const formatDateTime = (dt) => {
      if (!dt) return '—'
      return new Date(dt).toLocaleString('es-ES', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      })
    }

    onMounted(async () => {
      await Promise.all([loadJobs(), loadDomains()])
    })

    return {
      jobs, domains, loading,
      showForm, editing, form, formError, saving,
      testingSftp, sftpTestMsg, sftpTestOk,
      testingS3, s3TestMsg, s3TestOk, testS3,
      runningJobId,
      showHistory, historyJob, records, historyLoading, expanded,
      showRestore, restoreJob, snapshots, snapshotsLoading, restoreOpts, restoringSnap,
      domainName, statusLabel, statusClass,
      openCreate, openEdit, closeForm, submitForm, testSftp,
      runJob, openHistory, deleteJob,
      openRestore, doRestore, formatSnapshot,
      formatDate, formatDateTime,
      schedPreset, presetHour, schedSummary, applyPreset, cronSummary,
    }
  }
}
</script>

<style scoped>
/* Cabecera */
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: var(--sp-5); flex-wrap: wrap; }
.page-head__title { font-size: 1.5rem; font-weight: var(--fw-bold, 700); margin: 0; letter-spacing: -.01em; }
.page-head__sub { color: var(--text-muted); margin: .25rem 0 0; font-size: var(--fs-sm); }

/* Aviso informativo */
.bk-info { display: flex; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); background: var(--info-bg, var(--surface-inset)); border: 1px solid var(--info-border, var(--border)); border-radius: var(--r-md); margin-bottom: var(--sp-4); font-size: var(--fs-sm); color: var(--text-secondary); }
.bk-info > i { color: var(--info, var(--svq-orange)); font-size: 1.05rem; margin-top: 2px; flex-shrink: 0; }

.bk-center { display: flex; justify-content: center; padding: var(--sp-6) 0; color: var(--text-muted); }
.bk-muted { color: var(--text-muted); font-size: var(--fs-sm); }
.bk-name { font-weight: var(--fw-semibold); color: var(--text); }

/* Tabla */
.bk-table-wrap { overflow-x: auto; }
.bk-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.bk-table thead th { text-align: left; padding: var(--sp-3) var(--sp-4); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: var(--fw-semibold); border-bottom: 1px solid var(--border); white-space: nowrap; }
.bk-table tbody td { padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); vertical-align: middle; }
.bk-table tbody tr:last-child td { border-bottom: none; }
.bk-table tbody tr:hover { background: var(--surface-inset); }
.bk-table--sm thead th, .bk-table--sm tbody td { padding: var(--sp-2) var(--sp-3); }
.bk-row--off { opacity: .55; }
.bk-right { text-align: right; }

/* Tags / badges */
.bk-tag { display: inline-block; font-size: var(--fs-xs); font-weight: var(--fw-semibold); padding: 2px 8px; border-radius: var(--r-pill); margin-right: 4px; background: var(--surface-inset); color: var(--text-secondary); border: 1px solid var(--border); }
.bk-tag--web  { background: var(--brand-50); color: var(--color-primary); border-color: transparent; }
.bk-tag--db   { background: var(--info-bg, #e0f2fe); color: var(--info, #0369a1); border-color: transparent; }
.bk-tag--mail { background: var(--warning-bg); color: var(--warning); border-color: transparent; }
.bk-tag--inc  { background: var(--success-bg); color: var(--success); border-color: transparent; }
.bk-tag--full { background: var(--surface-inset); color: var(--text-muted); }

/* Estado */
.bk-status { display: inline-block; font-size: var(--fs-xs); font-weight: var(--fw-semibold); padding: 2px 9px; border-radius: var(--r-pill); }
.bk-status--ok   { background: var(--success-bg); color: var(--success); }
.bk-status--err  { background: var(--danger-bg); color: var(--danger); }
.bk-status--run  { background: var(--brand-50); color: var(--color-primary); }
.bk-status--idle { background: var(--surface-inset); color: var(--text-muted); }
.bk-sched { color: var(--success); }
.bk-running { color: var(--color-primary); display: inline-flex; align-items: center; gap: 5px; }

/* Botones de acción */
.bk-actions { display: inline-flex; gap: 4px; }
.bk-iconbtn { width: 30px; height: 30px; display: inline-grid; place-items: center; border: 1px solid var(--border); background: var(--surface); color: var(--text-secondary); border-radius: var(--r-sm); cursor: pointer; transition: all .12s; }
.bk-iconbtn:hover:not(:disabled) { background: var(--surface-inset); color: var(--text); border-color: var(--border-strong); }
.bk-iconbtn:disabled { opacity: .4; cursor: not-allowed; }
.bk-iconbtn--danger:hover:not(:disabled) { color: var(--danger); border-color: var(--danger); }

/* Modal */
.bk-modal { position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,.5); display: flex; align-items: flex-start; justify-content: center; padding: 4vh 1rem; overflow-y: auto; }
.bk-modal__dialog { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-lg, 0 20px 60px rgba(0,0,0,.3)); width: 100%; max-width: 640px; }
.bk-modal__dialog--lg { max-width: 800px; }
.bk-modal__dialog--xl { max-width: 900px; }
.bk-modal__head { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-4) var(--sp-5); border-bottom: 1px solid var(--border); background: var(--surface-inset); border-radius: var(--r-lg) var(--r-lg) 0 0; }
.bk-modal__title { margin: 0; font-size: var(--fs-md); font-weight: var(--fw-semibold); display: flex; align-items: center; gap: .5rem; }
.bk-modal__title .bi { color: var(--svq-orange); }
.bk-modal__close { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.1rem; padding: 4px; border-radius: var(--r-sm); }
.bk-modal__close:hover { background: var(--surface); color: var(--text); }
.bk-modal__body { padding: var(--sp-5); }
.bk-modal__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); padding: var(--sp-4) var(--sp-5); border-top: 1px solid var(--border); }
.bk-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
.bk-form-grid > div { display: flex; flex-direction: column; gap: 1rem; }

.bk-warn { display: flex; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); background: var(--warning-bg); border: 1px solid var(--warning-border); border-radius: var(--r-md); font-size: var(--fs-sm); color: var(--text-secondary); margin-bottom: var(--sp-4); }
.bk-warn > i { color: var(--warning); font-size: 1.05rem; margin-top: 2px; flex-shrink: 0; }
.bk-sublabel { display: block; font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); margin-bottom: var(--sp-2); }
.bk-restore-opts { display: flex; flex-wrap: wrap; gap: var(--sp-4); margin-bottom: var(--sp-4); }
.bk-alert-error { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger-border); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md); font-size: var(--fs-sm); }
.bk-logcell { background: var(--surface-inset); }
.bk-logerr { color: var(--danger); font-size: var(--fs-sm); margin-bottom: var(--sp-2); }
.bk-log { font-size: var(--fs-xs); font-family: var(--font-mono); max-height: 240px; overflow: auto; white-space: pre-wrap; margin: 0; color: var(--text-secondary); }

.bk-section {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md, 8px);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: .65rem;
}
.bk-section-title {
  font-size: .8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  margin-bottom: .1rem;
}
.bk-field {
  display: flex;
  flex-direction: column;
  gap: .25rem;
}
.bk-field label {
  font-size: .8rem;
  font-weight: 600;
  color: var(--text-secondary);
}
.bk-hint {
  font-size: .75rem;
  color: var(--text-muted);
}
.bk-check {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  font-size: .875rem;
  cursor: pointer;
  user-select: none;
}
.bk-check input { cursor: pointer; }

@media (max-width: 768px) {
  .bk-form-grid { grid-template-columns: 1fr; }
}
</style>
