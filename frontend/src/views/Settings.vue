<template>
  <div>
    <h2 class="mb-4"><i class="bi bi-gear"></i> Configuración</h2>

    <div class="card">
      <div class="card-header">
        <i class="bi bi-info-circle"></i> Información del Panel
      </div>
      <div class="card-body">
        <table class="table table-borderless">
          <tbody>
            <tr>
              <td><strong>Nombre:</strong></td>
              <td>SVQPanel</td>
            </tr>
            <tr>
              <td><strong>Versión:</strong></td>
              <td>0.1.0</td>
            </tr>
            <tr>
              <td><strong>API:</strong></td>
              <td>http://localhost:8001</td>
            </tr>
            <tr>
              <td><strong>Estado:</strong></td>
              <td><span class="badge bg-success">En línea</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card mt-4">
      <div class="card-header">
        <i class="bi bi-database"></i> Base de Datos
      </div>
      <div class="card-body">
        <table class="table table-borderless">
          <tbody>
            <tr>
              <td><strong>Servidor:</strong></td>
              <td>PostgreSQL</td>
            </tr>
            <tr>
              <td><strong>Estado:</strong></td>
              <td><span class="badge bg-success">Conectado</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Settings'
}
</script>
