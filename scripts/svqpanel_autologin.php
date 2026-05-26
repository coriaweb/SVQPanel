<?php
/**
 * SVQPanel Autologin Plugin para Roundcube
 *
 * Permite iniciar sesión automáticamente en Roundcube desde el panel SVQPanel
 * mediante un token de un solo uso de 60 segundos.
 *
 * Flujo:
 *   1. El panel SVQPanel genera un token  →  POST /api/mail/domains/{id}/mailboxes/{id}/webmail-token
 *   2. El panel abre en nueva pestaña:      https://servidor/webmail/?svqtoken=TOKEN
 *   3. Este plugin intercepta el startup de Roundcube
 *   4. Valida el token contra el endpoint interno del panel (solo localhost)
 *   5. Llama a $rcmail->login() con las credenciales recibidas
 *   6. Replica los pasos que normalmente hace index.php tras un login válido:
 *        - session->regenerate_id(false)
 *        - session->set_auth_cookie()       ← imprescindible: emite roundcube_sessauth
 *   7. Redirige a la bandeja de entrada
 *
 * Por qué hacen falta esos pasos manualmente:
 *   rcmail::login() solo autentica contra IMAP y rellena $_SESSION['user_id'].
 *   No regenera el session ID ni emite la cookie roundcube_sessauth — eso lo
 *   hace el handler de la acción "login" en /webmail/public_html/index.php.
 *   Al invocar login() desde un hook "startup" se salta ese paso, la cookie
 *   roundcube_sessauth nunca se envía y la siguiente petición pierde la sesión.
 *
 * Seguridad:
 *   - El endpoint interno solo acepta peticiones desde 127.0.0.1
 *   - Cada token es UUID aleatorio de 32 caracteres hexadecimales
 *   - El token caduca a los 60 segundos
 *   - El token se invalida tras el primer uso (single-use)
 */
class svqpanel_autologin extends rcube_plugin
{
    /** Enlaza con todos los tasks para poder interceptar el startup */
    public $task = '.*';

    /** No necesita frame ni AJAX propio */
    public $noframe = true;
    public $noajax  = false;

    /** Puerto del panel SVQPanel (debe coincidir con PANEL_PORT en .env) */
    private const PANEL_PORT = 8001;

    /** Tiempo máximo de espera para la llamada al panel (segundos) */
    private const FETCH_TIMEOUT = 5;

    // ------------------------------------------------------------------

    public function init(): void
    {
        $this->add_hook('startup', [$this, 'startup']);
    }

    /**
     * Hook startup: si hay un svqtoken en la URL, intenta autologin.
     */
    public function startup(array $args): array
    {
        // Si ya hay un usuario autenticado, no hacer nada
        if (!empty($_SESSION['user_id'])) {
            return $args;
        }

        // Solo actuar si el parámetro svqtoken está presente
        $raw_token = rcube_utils::get_input_value('svqtoken', rcube_utils::INPUT_GET);
        if (!$raw_token) {
            return $args;
        }

        // Validar formato del token (UUID hex de 32 chars, sin guiones)
        $token = preg_replace('/[^a-f0-9]/', '', strtolower($raw_token));
        if (strlen($token) !== 32) {
            return $args;
        }

        // Obtener credenciales del panel (llamada localhost)
        $data = $this->fetch_credentials($token);
        if (!$data || empty($data['username']) || empty($data['password'])) {
            return $args;
        }

        $rcmail = rcube::get_instance();
        $host   = $data['imap_host'] ?? 'localhost';

        if (!$rcmail->login($data['username'], $data['password'], $host, false)) {
            // Login fallido: dejar que Roundcube muestre la página normal de login
            return $args;
        }

        // ─── Replica el cierre de la acción "login" del index.php ────────────
        // (program/include/index.php líneas ~119-126 en Roundcube 1.7)
        $rcmail->session->remove('temp');
        $rcmail->session->regenerate_id(false);
        $rcmail->session->set_auth_cookie();   // ← emite la cookie roundcube_sessauth

        // Permite a otros plugins controlar la URL post-login
        $redir = $rcmail->plugins->exec_hook('login_after', ['_task' => 'mail']);
        unset($redir['abort'], $redir['_err']);

        $rcmail->output->redirect($redir, 0, true);
        exit;
    }

    // ------------------------------------------------------------------

    /**
     * Llama al endpoint interno del panel para validar el token
     * y obtener las credenciales IMAP.
     *
     * @param  string $token  Token UUID hex de 32 chars
     * @return array|null     ['username', 'password', 'imap_host', 'imap_port'] o null
     */
    private function fetch_credentials(string $token): ?array
    {
        $url = sprintf(
            'http://127.0.0.1:%d/api/internal/webmail-token/%s',
            self::PANEL_PORT,
            rawurlencode($token)
        );

        $context = stream_context_create([
            'http' => [
                'method'         => 'GET',
                'timeout'        => self::FETCH_TIMEOUT,
                'ignore_errors'  => true,
                'header'         => "Accept: application/json\r\n",
            ],
        ]);

        $response = @file_get_contents($url, false, $context);
        if ($response === false || $response === '') {
            return null;
        }

        $data = json_decode($response, true);
        if (json_last_error() !== JSON_ERROR_NONE) {
            return null;
        }

        // El panel devuelve 404/410 con {"detail": "..."} si el token no es válido
        if (isset($data['detail'])) {
            return null;
        }

        return $data;
    }
}
