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
        <strong>correo</strong>) de un dominio. Las copias son <strong>incrementales y cifradas</strong>
        (motor restic): solo se guarda lo que cambió —ocupan poquísimo aunque guardes mucho histórico— y los
        datos viajan y se almacenan encriptados. Puedes guardar las copias en <strong>este servidor</strong>,
        en <strong>otro servidor</strong> (SFTP) o en la <strong>nube</strong> (S3 / Backblaze); lo ideal es
        tener al menos una copia <strong>fuera</strong> del servidor.
      </div>
    </div>

    <!-- Actividad reciente (copias + restauraciones, con estado en vivo) -->
    <div v-if="activity.length" class="bk-activity">
      <div class="bk-activity__head">
        <span><i class="bi bi-activity"></i> Actividad reciente</span>
        <span v-if="activityRunning" class="bk-activity__live">
          <span class="spinner-border spinner-border-sm"></span> En curso…
        </span>
      </div>
      <div class="bk-activity__list">
        <div v-for="a in activity.slice(0, 6)" :key="a.id" class="bk-activity__row">
          <span class="bk-tag" :class="a.kind === 'restore' ? 'bk-tag--inc' : 'bk-tag--web'">
            <i :class="a.kind === 'restore' ? 'bi bi-arrow-counterclockwise' : 'bi bi-hdd'"></i>
            {{ a.kind === 'restore' ? 'Restauración' : 'Copia' }}
          </span>
          <span class="bk-activity__job">{{ a.job_name }}</span>
          <span class="bk-activity__date">{{ formatDateTime(a.started_at) }}</span>
          <span class="bk-activity__status">
            <span v-if="a.status === 'running' || a.status === 'pending'" class="bk-running">
              <span class="spinner-border spinner-border-sm"></span> {{ a.status === 'pending' ? 'En cola' : 'En proceso' }}
            </span>
            <span v-else class="bk-status" :class="statusClass(a.status)">{{ statusLabel(a.status) }}</span>
          </span>
        </div>
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
                <div class="bk-name">
                  {{ job.name }}
                  <span v-if="job.managed_by_admin" class="bk-tag bk-tag--admin" title="Backup configurado por el administrador">
                    <i class="bi bi-shield-lock"></i> Admin
                  </span>
                </div>
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
                  <!-- Ejecutar/editar/eliminar: solo para jobs propios (no los del admin) -->
                  <button v-if="!job.managed_by_admin" class="bk-iconbtn" title="Ejecutar ahora"
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
                  <button v-if="!job.managed_by_admin" class="bk-iconbtn" title="Editar" @click="openEdit(job)">
                    <i class="bi bi-pencil"></i>
                  </button>
                  <button v-if="!job.managed_by_admin" class="bk-iconbtn bk-iconbtn--danger" title="Eliminar" @click="deleteJob(job)">
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
                <div class="bk-section-title">¿Dónde se guarda la copia?</div>
                <div style="display:flex;gap:1.5rem;margin-bottom:.6rem;flex-wrap:wrap">
                  <label class="bk-check">
                    <input type="radio" value="local" v-model="form.destination_type" />
                    <i class="bi bi-hdd"></i> Este servidor
                  </label>
                  <label class="bk-check">
                    <input type="radio" value="sftp" v-model="form.destination_type" />
                    <i class="bi bi-hdd-network"></i> Otro servidor (SFTP)
                  </label>
                  <label class="bk-check">
                    <input type="radio" value="s3" v-model="form.destination_type" />
                    <i class="bi bi-cloud-arrow-up"></i> Nube (S3 / Backblaze)
                  </label>
                </div>
                <!-- Explicación según el destino elegido -->
                <p class="bk-dest-explain">
                  <template v-if="form.destination_type === 'local'">
                    <i class="bi bi-info-circle"></i> La copia se guarda en el <strong>disco de este mismo servidor</strong>.
                    Es lo más rápido, pero <strong>si el servidor o su disco fallan, pierdes también las copias</strong>.
                    Recomendado combinarlo con un destino externo.
                  </template>
                  <template v-else-if="form.destination_type === 'sftp'">
                    <i class="bi bi-info-circle"></i> La copia se envía por <strong>SSH/SFTP a otro servidor tuyo</strong>
                    (por ejemplo un NAS o un VPS de respaldo). Necesitas los datos de acceso de ese otro servidor.
                  </template>
                  <template v-else>
                    <i class="bi bi-info-circle"></i> La copia se sube a un <strong>almacenamiento en la nube</strong>
                    (fuera de este servidor). Es la opción más segura ante desastres. Si nunca lo has usado,
                    <a href="#" @click.prevent="showS3Help = !showS3Help">{{ showS3Help ? 'ocultar la guía' : 'lee la guía rápida 👇' }}</a>.
                  </template>
                </p>

                <div v-if="form.destination_type === 'local'" class="bk-field">
                  <label>Carpeta en el servidor</label>
                  <input v-model="form.local_path" class="form-control form-control-sm font-monospace" placeholder="/backups" />
                  <span class="bk-hint">Ruta donde se guardarán las copias. Por defecto <code>/backups</code> está bien.</span>
                </div>

                <!-- S3 / compatible -->
                <div v-else-if="form.destination_type === 's3'" style="display:flex;flex-direction:column;gap:.75rem">

                  <!-- Guía rápida desplegable -->
                  <div v-if="showS3Help" class="bk-s3-guide">
                    <div class="bk-s3-guide__title"><i class="bi bi-lightbulb"></i> ¿Qué es esto y cómo lo consigo? (en 2 minutos)</div>
                    <p>
                      «S3» es un estándar para guardar archivos en la nube. Muchas empresas lo ofrecen; la más
                      <strong>barata y sencilla para empezar es Backblaze B2</strong> (10&nbsp;GB gratis).
                    </p>
                    <ol>
                      <li>Crea una cuenta en <strong>backblaze.com</strong> → entra en <em>B2 Cloud Storage</em>.</li>
                      <li>Pulsa <strong>«Create a Bucket»</strong>, ponle un nombre (ej. <code>misuper-backups</code>) y guárdalo.
                          → ese nombre es el campo <strong>Bucket</strong> de abajo.</li>
                      <li>En la pantalla del bucket verás <strong>«Endpoint»</strong> (algo como
                          <code>s3.us-west-002.backblazeb2.com</code>). Cópialo al campo <strong>Endpoint</strong>.
                          La parte <code>us-west-002</code> es la <strong>Región</strong>.</li>
                      <li>Ve a <strong>«App Keys»</strong> → <strong>«Add a New Application Key»</strong>. Te dará dos
                          códigos: <em>keyID</em> y <em>applicationKey</em>. Son el <strong>Access Key</strong> y el
                          <strong>Secret Key</strong>. <u>Copia el Secret en el momento</u>: solo se muestra una vez.</li>
                    </ol>
                    <p style="margin:0">
                      Con AWS, DigitalOcean Spaces, Wasabi, etc. el proceso es equivalente (bucket + endpoint + 2 claves).
                      Cuando lo tengas, rellena los campos y pulsa <strong>«Probar conexión»</strong>.
                    </p>
                  </div>

                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Bucket <span class="text-danger">*</span></label>
                      <input v-model="form.s3_bucket" class="form-control form-control-sm" placeholder="misuper-backups" />
                      <span class="bk-hint">El nombre del «cubo» que creaste en tu proveedor.</span>
                    </div>
                    <div class="bk-field">
                      <label>Carpeta (opcional)</label>
                      <input v-model="form.s3_prefix" class="form-control form-control-sm font-monospace" placeholder="svqpanel/" />
                      <span class="bk-hint">Subcarpeta dentro del bucket. Puedes dejarlo vacío.</span>
                    </div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Endpoint <span class="bk-hint">(en blanco si usas AWS)</span></label>
                      <input v-model="form.s3_endpoint" class="form-control form-control-sm" placeholder="s3.us-west-002.backblazeb2.com" />
                      <span class="bk-hint">La «dirección» del servicio. Te la da tu proveedor.</span>
                    </div>
                    <div class="bk-field">
                      <label>Región</label>
                      <input v-model="form.s3_region" class="form-control form-control-sm" placeholder="us-west-002" />
                      <span class="bk-hint">Suele ser parte del endpoint (ej. <code>us-west-002</code>).</span>
                    </div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
                    <div class="bk-field">
                      <label>Access Key (keyID) <span class="text-danger">*</span></label>
                      <input v-model="form.s3_access_key" class="form-control form-control-sm font-monospace" placeholder="000abc..." />
                      <span class="bk-hint">El identificador de tu clave de acceso.</span>
                    </div>
                    <div class="bk-field">
                      <label>Secret Key</label>
                      <input v-model="form.s3_secret_key" type="password" class="form-control form-control-sm"
                             :placeholder="editing ? 'Sin cambios' : 'La clave secreta'" />
                      <span class="bk-hint">La clave secreta (solo se muestra una vez al crearla).</span>
                    </div>
                  </div>
                  <p class="bk-hint" style="margin:0">
                    <i class="bi bi-shield-check"></i> La copia se sube comprimida (.tar.gz) y la clave secreta se guarda cifrada.
                    Funciona con AWS S3, Backblaze B2, Wasabi, DigitalOcean Spaces, MinIO…
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
                  <p v-if="!editing" class="bk-hint" style="margin:0">
                    <i class="bi bi-info-circle"></i> Guarda primero el backup y luego podrás usar «Probar conexión» para comprobar las credenciales.
                  </p>
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
                  <tr v-if="expanded === r.id">
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
          <!-- Selector de dominio (cuando el backup cubre varios) -->
          <div v-if="restoreDomains.length > 1" class="bk-field" style="max-width:360px;margin-bottom:1rem">
            <label>Dominio a restaurar</label>
            <select v-model="selectedRestoreDomain" class="form-select form-select-sm"
                    @change="restoreStep = 1; loadRestoreSnapshots()">
              <option value="" disabled>Elige un dominio…</option>
              <option v-for="d in restoreDomains" :key="d.domain" :value="d.domain">{{ d.domain }}</option>
            </select>
          </div>

          <!-- PASO 1: elegir la copia -->
          <template v-if="restoreStep === 1">
            <p class="bk-muted" style="margin:0 0 .6rem">Elige el punto en el tiempo al que quieres volver:</p>
            <div v-if="snapshotsLoading" class="bk-center"><div class="spinner-border spinner-border-sm"></div></div>
            <EmptyState v-else-if="restoreDomains.length > 1 && !selectedRestoreDomain" icon="hdd"
                        title="Elige un dominio" description="Este backup cubre varios dominios. Selecciona arriba cuál restaurar." />
            <EmptyState v-else-if="snapshots.length === 0" icon="hdd"
                        title="Sin copias" description="Aún no hay copias para este dominio. Ejecuta el backup primero." />
            <div v-else class="bk-table-wrap">
              <table class="bk-table bk-table--sm">
                <thead><tr><th>Fecha de la copia</th><th>ID</th><th class="bk-right"></th></tr></thead>
                <tbody>
                  <tr v-for="s in snapshots" :key="s.id">
                    <td class="bk-muted">{{ formatDateTime(s.time) }}</td>
                    <td class="bk-muted"><code>{{ s.id }}</code></td>
                    <td class="bk-right">
                      <BaseButton variant="primary" size="sm" :loading="loadingContents === s.id" @click="chooseSnapshot(s)">
                        Elegir <i class="bi bi-arrow-right"></i>
                      </BaseButton>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <!-- PASO 2: qué y cómo restaurar -->
          <template v-else-if="restoreStep === 2">
            <button class="bk-link" @click="restoreStep = 1"><i class="bi bi-arrow-left"></i> Cambiar copia</button>
            <p class="bk-muted" style="margin:.4rem 0 .8rem">
              Copia del <strong>{{ formatDateTime(chosenSnap?.time) }}</strong>. Elige qué restaurar y cómo:
            </p>

            <!-- Qué restaurar -->
            <div class="bk-section">
              <div class="bk-section-title">¿Qué quieres restaurar?</div>
              <div v-if="contentsLoading" class="bk-center"><div class="spinner-border spinner-border-sm"></div></div>
              <template v-else>
                <!-- Copia antigua (sin estructura granular): se restaura completa -->
                <div v-if="contents.legacy" class="bk-warn" style="margin:0">
                  <i class="bi bi-clock-history"></i>
                  <div>
                    Esta copia es de un <strong>formato anterior</strong>, así que no se puede elegir por
                    partes: se restaurará <strong>completa</strong> a la carpeta de recuperación. Las copias
                    nuevas sí permiten elegir web / BD / buzones por separado.
                  </div>
                </div>
                <template v-else>
                  <label v-if="contents.web" class="bk-check bk-check--row">
                    <input type="checkbox" v-model="sel.web" /><i class="bi bi-folder"></i> Web (archivos del sitio)
                  </label>
                  <div v-if="contents.databases && contents.databases.length">
                    <div class="bk-muted" style="margin:.5rem 0 .2rem"><i class="bi bi-database"></i> Bases de datos:</div>
                    <label v-for="d in contents.databases" :key="d" class="bk-check bk-check--row" style="margin-left:1rem">
                      <input type="checkbox" :value="d" v-model="sel.databases" /> {{ d }}
                    </label>
                  </div>
                  <div v-if="contents.mail && contents.mail.length">
                    <div class="bk-muted" style="margin:.5rem 0 .2rem"><i class="bi bi-envelope"></i> Buzones de correo:</div>
                    <label v-for="m in contents.mail" :key="m" class="bk-check bk-check--row" style="margin-left:1rem">
                      <input type="checkbox" :value="m" v-model="sel.mail" /> {{ m }}
                    </label>
                  </div>
                  <p v-if="!contents.web && !contents.databases.length && !contents.mail.length" class="bk-muted">
                    Esta copia no tiene contenido restaurable.
                  </p>
                </template>
              </template>
            </div>

            <!-- Cómo restaurar -->
            <div class="bk-section">
              <div class="bk-section-title">¿Cómo restaurar?</div>
              <label class="bk-radio">
                <input type="radio" :value="false" v-model="restoreOverwrite" />
                <div>
                  <strong>A una carpeta de recuperación</strong> (seguro)
                  <div class="bk-muted">Descarga la copia en <code>~/restore/</code> sin tocar lo actual. Revisas y copias lo que necesites.</div>
                </div>
              </label>
              <label class="bk-radio">
                <input type="radio" :value="true" v-model="restoreOverwrite" />
                <div>
                  <strong style="color:var(--danger,#dc3545)">Sobrescribir en vivo</strong> (vuelve al estado de esta copia)
                  <div class="bk-muted">Reemplaza la web/BD/correo actuales por los de la copia. <strong>Lo actual se pierde.</strong></div>
                </div>
              </label>
            </div>
          </template>
        </div>
        <div class="bk-modal__foot">
          <BaseButton variant="ghost" size="sm" @click="showRestore = false">Cerrar</BaseButton>
          <BaseButton v-if="restoreStep === 2" :variant="restoreOverwrite ? 'danger' : 'primary'" size="sm"
                      :loading="!!restoringSnap"
                      :disabled="!sel.legacy && !sel.web && !sel.databases.length && !sel.mail.length"
                      @click="doRestore">
            <i class="bi bi-arrow-counterclockwise"></i>
            {{ restoreOverwrite ? 'Sobrescribir ahora' : 'Restaurar a carpeta' }}
          </BaseButton>
        </div>
      </div>
    </div>

    <!-- Modal: contraseña de cifrado restic (se muestra UNA vez al crear) -->
    <div v-if="showResticPassword" class="bk-modal-backdrop" @click.self="showResticPassword = false">
      <div class="bk-modal" style="max-width:520px">
        <div class="bk-modal__head">
          <h3><i class="bi bi-key-fill" style="color:var(--svq-orange)"></i> Guarda esta contraseña</h3>
        </div>
        <div class="bk-modal__body">
          <div class="bk-info" style="border-left:3px solid var(--danger,#dc3545)">
            <i class="bi bi-exclamation-triangle-fill" style="color:var(--danger,#dc3545)"></i>
            <div>
              Tus copias se guardan <strong>cifradas</strong> con esta contraseña. <strong>Anótala y guárdala
              en lugar seguro</strong>: sin ella, los backups son <strong>imposibles de recuperar</strong>.
              Solo se muestra <strong>ahora</strong>.
            </div>
          </div>
          <div style="display:flex;gap:.5rem;align-items:center;margin-top:1rem">
            <input :value="resticPasswordShown" readonly class="form-control font-monospace"
                   style="font-size:1.05rem;letter-spacing:.5px" @focus="$event.target.select()" />
            <BaseButton variant="secondary" size="sm" @click="copyResticPassword">
              <i class="bi bi-clipboard"></i> Copiar
            </BaseButton>
          </div>
        </div>
        <div class="bk-modal__foot">
          <BaseButton variant="primary" size="sm" @click="showResticPassword = false">
            La he guardado
          </BaseButton>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
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
    const showS3Help = ref(false)
    const showResticPassword = ref(false)
    const resticPasswordShown = ref('')

    const runningJobId = ref(null)

    const showHistory = ref(false)
    const historyJob = ref(null)
    const records = ref([])
    const historyLoading = ref(false)
    const expanded = ref(null)

    const showRestore = ref(false)
    const restoreJob = ref(null)
    const restoreDomains = ref([])
    const selectedRestoreDomain = ref('')
    const snapshots = ref([])
    const snapshotsLoading = ref(false)
    const restoreOpts = ref({ files: true, databases: true, mail: false })
    const restoringSnap = ref(null)
    // Restauración granular (paso 2)
    const restoreStep = ref(1)
    const chosenSnap = ref(null)
    const loadingContents = ref(null)
    const contentsLoading = ref(false)
    const contents = ref({ web: false, mail: [], databases: [] })
    const sel = ref({ web: false, mail: [], databases: [] })
    const restoreOverwrite = ref(false)

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

    // ── Actividad reciente (copias + restauraciones, con estado en vivo) ──
    const activity = ref([])
    const activityRunning = computed(() =>
      activity.value.some(a => a.status === 'running' || a.status === 'pending'))
    let activityTimer = null

    const loadActivity = async () => {
      try {
        activity.value = await api.getBackupActivity() || []
      } catch (e) { /* silencioso */ }
      // Auto-refresco: rápido si hay algo en curso, lento si no.
      if (activityTimer) clearTimeout(activityTimer)
      activityTimer = setTimeout(loadActivity, activityRunning.value ? 3000 : 20000)
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
          const created = await api.createBackupJob(form.value)
          store.showNotification('Backup creado', 'success')
          // Mostrar UNA vez la contraseña de cifrado para que el usuario la anote
          if (created && created.restic_password_plain) {
            resticPasswordShown.value = created.restic_password_plain
            showResticPassword.value = true
          }
        }
        showForm.value = false
        await loadJobs()
      } catch (e) {
        formError.value = e.message
      } finally {
        saving.value = false
      }
    }

    const copyResticPassword = () => {
      navigator.clipboard?.writeText(resticPasswordShown.value)
        .then(() => store.showNotification('Contraseña copiada', 'success'))
        .catch(() => {})
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
        loadActivity()   // refrescar el panel de actividad de inmediato
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
      showRestore.value = true
      restoreStep.value = 1
      chosenSnap.value = null
      restoreOverwrite.value = false
      snapshotsLoading.value = true
      snapshots.value = []
      restoreDomains.value = []
      selectedRestoreDomain.value = ''
      try {
        // Qué dominios puede restaurar el usuario en este job (1 o varios)
        restoreDomains.value = await api.getBackupJobDomains(job.id)
        if (restoreDomains.value.length === 1) {
          selectedRestoreDomain.value = restoreDomains.value[0].domain
        }
        await loadRestoreSnapshots()
      } catch (e) {
        store.showNotification('Error cargando copias: ' + e.message, 'danger')
        snapshotsLoading.value = false
      }
    }

    const loadRestoreSnapshots = async () => {
      // Si hay varios dominios y no se ha elegido, no cargamos aún
      if (restoreDomains.value.length > 1 && !selectedRestoreDomain.value) {
        snapshots.value = []
        snapshotsLoading.value = false
        return
      }
      snapshotsLoading.value = true
      try {
        snapshots.value = await api.getBackupSnapshots(
          restoreJob.value.id, selectedRestoreDomain.value || null)
      } catch (e) {
        store.showNotification('Error cargando copias: ' + e.message, 'danger')
      } finally {
        snapshotsLoading.value = false
      }
    }

    // Paso 1 → 2: elegida la copia, cargar su contenido (web/buzones/BD)
    const chooseSnapshot = async (snap) => {
      loadingContents.value = snap.id
      contentsLoading.value = true
      try {
        chosenSnap.value = snap
        contents.value = await api.getSnapshotContents(
          restoreJob.value.id, snap.id, selectedRestoreDomain.value || null)
        // preseleccionar todo por defecto
        sel.value = {
          web: !!contents.value.web,
          databases: [...(contents.value.databases || [])],
          mail: [...(contents.value.mail || [])],
          legacy: !!contents.value.legacy,
        }
        // Copias antiguas solo permiten restaurar a carpeta (no sobrescribir granular)
        if (contents.value.legacy) restoreOverwrite.value = false
        restoreStep.value = 2
      } catch (e) {
        store.showNotification('Error leyendo la copia: ' + e.message, 'danger')
      } finally {
        loadingContents.value = null
        contentsLoading.value = false
      }
    }

    const doRestore = async () => {
      const snap = chosenSnap.value
      if (!snap) return
      const parts = []
      if (sel.value.legacy) parts.push('copia completa')
      if (sel.value.web) parts.push('web')
      if (sel.value.databases.length) parts.push(`${sel.value.databases.length} BD`)
      if (sel.value.mail.length) parts.push(`${sel.value.mail.length} buzón(es)`)

      if (restoreOverwrite.value) {
        if (!confirm(`⚠️ SOBRESCRIBIR ${parts.join(', ')} con la copia del ${formatDateTime(snap.time)}.\n\nLo actual se PERDERÁ y se reemplazará por el estado de esa copia. ¿Continuar?`)) return
      } else {
        if (!confirm(`Restaurar ${parts.join(', ')} de la copia del ${formatDateTime(snap.time)} a ~/restore/${snap.id}/ (no toca lo actual). ¿Continuar?`)) return
      }

      restoringSnap.value = snap.id
      try {
        const rec = await api.restoreBackup(restoreJob.value.id, {
          snapshot_name: snap.id,
          domain: selectedRestoreDomain.value || null,
          overwrite: restoreOverwrite.value,
          legacy: sel.value.legacy,
          web: sel.value.web,
          databases: sel.value.databases,
          mail: sel.value.mail,
        })
        store.showNotification('Restauración iniciada…', 'info')
        loadActivity()   // mostrar la restauración en el panel de actividad
        const final = await pollRecord(rec.id)
        if (final && final.status === 'success') {
          store.showNotification(restoreOverwrite.value
            ? 'Restauración aplicada correctamente' : `Restaurado en ~/restore/${snap.id}/`, 'success')
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
      loadActivity()
    })
    onUnmounted(() => { if (activityTimer) clearTimeout(activityTimer) })

    return {
      jobs, domains, loading,
      activity, activityRunning,
      showForm, editing, form, formError, saving,
      testingSftp, sftpTestMsg, sftpTestOk,
      testingS3, s3TestMsg, s3TestOk, testS3, showS3Help,
      showResticPassword, resticPasswordShown, copyResticPassword,
      runningJobId,
      showHistory, historyJob, records, historyLoading, expanded,
      showRestore, restoreJob, snapshots, snapshotsLoading, restoreOpts, restoringSnap,
      restoreDomains, selectedRestoreDomain, loadRestoreSnapshots,
      restoreStep, chosenSnap, loadingContents, contentsLoading,
      contents, sel, restoreOverwrite, chooseSnapshot,
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
/* Explicación del destino elegido */
.bk-dest-explain { font-size: var(--fs-sm); color: var(--text-secondary); margin: 0 0 .9rem; line-height: 1.5; }
.bk-dest-explain > i { color: var(--info, var(--svq-orange)); margin-right: 4px; }
.bk-dest-explain a { color: var(--svq-orange, #e8590c); font-weight: 600; }

/* Guía rápida de S3 */
.bk-s3-guide { background: var(--surface-inset, #f8fafc); border: 1px solid var(--border); border-left: 3px solid var(--svq-orange, #e8590c); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); font-size: var(--fs-sm); color: var(--text-secondary); line-height: 1.55; }
.bk-s3-guide__title { font-weight: 700; color: var(--text); margin-bottom: .4rem; }
.bk-s3-guide__title > i { color: var(--svq-orange, #e8590c); }
.bk-s3-guide p { margin: .35rem 0; }
.bk-s3-guide ol { margin: .4rem 0 .4rem 0; padding-left: 1.2rem; }
.bk-s3-guide li { margin: .3rem 0; }
.bk-s3-guide code { background: var(--surface, #fff); padding: 1px 5px; border-radius: 4px; border: 1px solid var(--border); font-size: .82em; }

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
.bk-tag--admin { background: var(--svq-orange, #e8590c); color: #fff; border-color: transparent; margin-left: .4rem; }
.bk-check--row { display: flex; align-items: center; gap: .5rem; padding: .25rem 0; cursor: pointer; }
.bk-radio { display: flex; align-items: flex-start; gap: .6rem; padding: .6rem; border: 1px solid var(--border); border-radius: var(--r-md); margin-bottom: .5rem; cursor: pointer; }
.bk-radio input { margin-top: .25rem; }
.bk-link { background: none; border: none; color: var(--svq-orange, #e8590c); cursor: pointer; font-size: .85rem; padding: 0; }
/* Panel de actividad reciente */
.bk-activity { border: 1px solid var(--border); border-radius: var(--r-md); margin-bottom: var(--sp-4); overflow: hidden; }
.bk-activity__head { display: flex; justify-content: space-between; align-items: center; padding: .5rem .9rem; background: var(--surface-inset, #f8fafc); font-weight: 600; font-size: .9rem; border-bottom: 1px solid var(--border); }
.bk-activity__live { color: var(--svq-orange, #e8590c); font-size: .82rem; font-weight: 500; display: inline-flex; align-items: center; gap: .4rem; }
.bk-activity__list { display: flex; flex-direction: column; }
.bk-activity__row { display: grid; grid-template-columns: 130px 1fr auto auto; gap: .75rem; align-items: center; padding: .5rem .9rem; border-bottom: 1px solid var(--border); font-size: .85rem; }
.bk-activity__row:last-child { border-bottom: none; }
.bk-activity__job { font-weight: 600; color: var(--text); }
.bk-activity__date { color: var(--text-muted); }
.bk-activity__status { text-align: right; }

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
