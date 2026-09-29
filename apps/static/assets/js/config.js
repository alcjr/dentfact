/**
 * config.js
 * Gestión completa de la interfaz de configuración para XLS2SFD
 * Alineado 100% con config.ini en c:\dentfact\config.ini
 * Requiere: Bootstrap 5, FontAwesome, jQuery (opcional)
 */

document.addEventListener('DOMContentLoaded', function () {
    // ================== VARIABLES GLOBALES ==================
    const CONFIG_PATH = 'c:\\dentfact\\config.ini';
    let originalConfig = {};  // Configuración original (para detectar cambios)
    let currentConfig = {};   // Configuración actual en memoria
    let hasUnsavedChanges = false;

    // Selectores
    const $saveBtn = document.getElementById('saveConfigBtn');
    const $reloadBtn = document.getElementById('reloadConfigBtn');
    const $validateBtn = document.getElementById('validateAllBtn');
    const $exportBtn = document.getElementById('exportConfigBtn');
    const $importBtn = document.getElementById('importConfigBtn');
    const $resetBtn = document.getElementById('resetDefaultsBtn');
    const $unsavedChanges = document.getElementById('unsavedChanges');
    const $loadingOverlay = document.getElementById('loadingOverlay');
    const $configFileName = document.getElementById('configFileName');
    const $configLastModified = document.getElementById('configLastModified');
    const $configPreview = document.getElementById('configPreview');
    const $refreshPreview = document.getElementById('refreshPreview');
    const $importFileInput = document.getElementById('importFileInput');

    // Inputs (todos los campos del formulario)
    const inputs = {
        // [inputs]
        inputsPdf: document.getElementById('inputsPdf'),
        inputsTablas: document.getElementById('inputsTablas'),
        inputsMaster: document.getElementById('inputsMaster'),

        // [outputs]
        outputsLogs: document.getElementById('outputsLogs'),
        outputsMerged: document.getElementById('outputsMerged'),
        outputsFacturas: document.getElementById('outputsFacturas'),
        outputsSqlite3Dbpath: document.getElementById('outputsSqlite3Dbpath'),

        // [smtp]
        smtpEmailHost: document.getElementById('smtpEmailHost'),
        smtpEmailPort: document.getElementById('smtpEmailPort'),
        smtpEmailUseSsl: document.getElementById('smtpEmailUseSsl'),
        smtpEmailUseTls: document.getElementById('smtpEmailUseTls'),
        smtpEmailHostUser: document.getElementById('smtpEmailHostUser'),
        smtpEmailHostPassword: document.getElementById('smtpEmailHostPassword'),

        // [default]
        defaultGabinetePercentage: document.getElementById('defaultGabinetePercentage'),
        defaultIvaPercentage: document.getElementById('defaultIvaPercentage'),
        defaultIrpfPercentage: document.getElementById('defaultIrpfPercentage'),
        defaultDdFemision: document.getElementById('defaultDdFemision'),
        defaultGastos: document.getElementById('defaultGastos')
    };

    // Feedback elements
    const feedback = {};
    Object.keys(inputs).forEach(key => {
        const feedbackId = key + 'Feedback';
        feedback[key] = document.getElementById(feedbackId);
    });

    // ================== INICIALIZACIÓN ==================
    init();

    function init() {
        $configFileName.textContent = CONFIG_PATH;
        loadConfig();
        setupEventListeners();
        updateLastModified();
        markUnsavedChanges(false);
    }

    // ================== CARGA DE CONFIGURACIÓN ==================
    function loadConfig() {
        showLoading(true);
        fetch('/api/config/load/', {
            method: 'GET',
            headers: { 'X-CSRFToken': getCSRFToken() }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                originalConfig = { ...data.config };
                currentConfig = { ...data.config };
                populateForm();
                updatePreview();
                updateLastModified(data.last_modified);
                showAlert('Configuración cargada correctamente', 'success');
            } else {
                showAlert('Error al cargar config.ini: ' + data.error, 'danger');
            }
        })
        .catch(err => {
            console.error(err);
            showAlert('Error de red al cargar configuración', 'danger');
        })
        .finally(() => showLoading(false));
    }

    function populateForm() {
        // [inputs]
        setValue('inputsPdf', currentConfig.inputs?.pdf);
        setValue('inputsTablas', currentConfig.inputs?.tablas);
        setValue('inputsMaster', currentConfig.inputs?.master);

        // [outputs]
        setValue('outputsLogs', currentConfig.outputs?.logs);
        setValue('outputsMerged', currentConfig.outputs?.merged);
        setValue('outputsFacturas', currentConfig.outputs?.facturas);
        setValue('outputsSqlite3Dbpath', currentConfig.outputs?.sqlite3_dbpath);

        // [smtp]
        setValue('smtpEmailHost', currentConfig.smtp?.email_host);
        setValue('smtpEmailPort', currentConfig.smtp?.email_port);
        setValue('smtpEmailUseSsl', currentConfig.smtp?.email_use_ssl === 'True' || currentConfig.smtp?.email_use_ssl === true, 'checkbox');
        setValue('smtpEmailUseTls', currentConfig.smtp?.email_use_tls === 'True' || currentConfig.smtp?.email_use_tls === true, 'checkbox');
        setValue('smtpEmailHostUser', currentConfig.smtp?.email_host_user);
        setValue('smtpEmailHostPassword', currentConfig.smtp?.email_host_password);

        // [default]
        setValue('defaultGabinetePercentage', currentConfig.default?.gabinete_percentage);
        setValue('defaultIvaPercentage', currentConfig.default?.iva_percentage);
        setValue('defaultIrpfPercentage', currentConfig.default?.irpf_percentage);
        setValue('defaultDdFemision', currentConfig.default?.dd_femision);
        setValue('defaultGastos', currentConfig.default?.gastos);
    }

    function setValue(id, value, type = 'text') {
        const el = inputs[id];
        if (!el) return;
        if (type === 'checkbox') {
            el.checked = value;
        } else {
            el.value = value || '';
        }
    }

    // ================== EVENT LISTENERS ==================
    function setupEventListeners() {
        // Botones principales
        $saveBtn.addEventListener('click', saveConfig);
        $reloadBtn.addEventListener('click', reloadConfig);
        $validateBtn.addEventListener('click', validateAll);
        $exportBtn.addEventListener('click', exportConfig);
        $importBtn.addEventListener('click', () => $importFileInput.click());
        $resetBtn.addEventListener('click', resetToDefaults);
        $refreshPreview.addEventListener('click', updatePreview);

        // Importar archivo
        $importFileInput.addEventListener('change', handleImport);

        // Cambios en inputs
        Object.values(inputs).forEach(input => {
            if (input) {
                input.addEventListener('input', () => {
                    markUnsavedChanges(true);
                    updatePreview();
                });
                input.addEventListener('change', () => validateField(input));
            }
        });

        // SMTP: probar conexión
        document.getElementById('testSmtpConnection').addEventListener('click', testSmtp);
        document.getElementById('sendTestEmail').addEventListener('click', sendTestEmail);

        // DB: probar conexión
        document.getElementById('testDatabaseConnection').addEventListener('click', testDatabase);

        // Toggle password
        document.getElementById('togglePassword').addEventListener('click', function () {
            const pwd = inputs.smtpEmailHostPassword;
            const icon = this.querySelector('i');
            if (pwd.type === 'password') {
                pwd.type = 'text';
                icon.classList.replace('fa-eye', 'fa-eye-slash');
            } else {
                pwd.type = 'password';
                icon.classList.replace('fa-eye-slash', 'fa-eye');
            }
        });

        // Browse buttons
        document.querySelectorAll('.btn-browse').forEach(btn => {
            btn.addEventListener('click', () => {
                const inputId = btn.id.replace('browse', '');
                const input = inputs[inputId];
                if (input) {
                    window.electronAPI?.browsePath(inputId).then(path => {
                        if (path) {
                            input.value = path;
                            markUnsavedChanges(true);
                            validateField(input);
                        }
                    });
                }
            });
        });
    }

    // ================== GUARDAR CONFIGURACIÓN ==================
    function saveConfig() {
        if (!validateAll(true)) return;

        const config = collectFormData();
        showLoading(true);

        fetch('/api/config/save/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({ config: config })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                originalConfig = { ...config };
                currentConfig = { ...config };
                markUnsavedChanges(false);
                updateLastModified(data.last_modified);
                showAlert('Configuración guardada correctamente', 'success');
            } else {
                showAlert('Error al guardar: ' + data.error, 'danger');
            }
        })
        .catch(err => {
            console.error(err);
            showAlert('Error de red al guardar', 'danger');
        })
        .finally(() => showLoading(false));
    }

    function collectFormData() {
        return {
            inputs: {
                pdf: inputs.inputsPdf.value.trim(),
                tablas: inputs.inputsTablas.value.trim(),
                master: inputs.inputsMaster.value.trim()
            },
            outputs: {
                logs: inputs.outputsLogs.value.trim(),
                merged: inputs.outputsMerged.value.trim(),
                facturas: inputs.outputsFacturas.value.trim(),
                sqlite3_dbpath: inputs.outputsSqlite3Dbpath.value.trim()
            },
            smtp: {
                email_host: inputs.smtpEmailHost.value.trim(),
                email_port: parseInt(inputs.smtpEmailPort.value) || 465,
                email_use_ssl: inputs.smtpEmailUseSsl.checked ? 'True' : 'False',
                email_use_tls: inputs.smtpEmailUseTls.checked ? 'True' : 'False',
                email_host_user: inputs.smtpEmailHostUser.value.trim(),
                email_host_password: inputs.smtpEmailHostPassword.value
            },
            default: {
                gabinete_percentage: inputs.defaultGabinetePercentage.value,
                iva_percentage: inputs.defaultIvaPercentage.value,
                irpf_percentage: inputs.defaultIrpfPercentage.value,
                dd_femision: inputs.defaultDdFemision.value.padStart(2, '0'),
                gastos: inputs.defaultGastos.value
            }
        };
    }

    // ================== RECARGAR ==================
    function reloadConfig() {
        if (hasUnsavedChanges && !confirm('¿Descartar cambios sin guardar?')) return;
        loadConfig();
        markUnsavedChanges(false);
    }

    // ================== VALIDACIÓN ==================
    function validateAll(silent = false) {
        let allValid = true;
        Object.values(inputs).forEach(input => {
            if (input && !validateField(input, silent)) {
                allValid = false;
            }
        });
        return allValid;
    }

    function validateField(input, silent = false) {
        const id = input.id;
        const value = input.type === 'checkbox' ? input.checked : input.value.trim();
        const feedbackEl = feedback[id];

        if (!feedbackEl) return true;

        let valid = true;
        let message = '';

        // Validaciones por campo
        if (id.includes('Pdf') || id.includes('Tablas') || id.includes('Master') ||
            id.includes('Logs') || id.includes('Merged') || id.includes('Facturas')) {
            if (!value) {
                valid = false;
                message = 'Este campo es obligatorio';
            } else if (!isValidPath(value)) {
                valid = false;
                message = 'Ruta no válida o inaccesible';
            }
        }

        if (id === 'outputsSqlite3Dbpath') {
            if (!value.endsWith('.sqlite3') && !value.endsWith('.db')) {
                valid = false;
                message = 'Debe ser un archivo .sqlite3 o .db';
            }
        }

        if (id === 'smtpEmailHost') {
            if (!value.includes('.')) {
                valid = false;
                message = 'Dominio SMTP no válido';
            }
        }

        if (id === 'smtpEmailPort') {
            const port = parseInt(value);
            if (isNaN(port) || port < 1 || port > 65535) {
                valid = false;
                message = 'Puerto inválido';
            }
        }

        if (id === 'smtpEmailHostUser') {
            if (!value.includes('@')) {
                valid = false;
                message = 'Email no válido';
            }
        }

        if (id === 'defaultDdFemision') {
            if (!/^\d{1,2}$/.test(value) || parseInt(value) < 1 || parseInt(value) > 31) {
                valid = false;
                message = 'Día entre 01 y 31';
            }
        }

        // Mostrar feedback
        feedbackEl.className = 'validation-feedback ' + (valid ? 'valid' : 'invalid');
        feedbackEl.textContent = valid ? 'Válido' : message;

        if (!silent && !valid) {
            input.focus();
        }

        return valid;
    }

    function isValidPath(path) {
        // Simulación: en entorno real, usar backend o Electron
        return path && path.length > 3 && /[a-zA-Z]:\\.*/.test(path);
    }

    // ================== VISTA PREVIA ==================
    function updatePreview() {
        const config = collectFormData();
        let ini = '';

        for (const [section, values] of Object.entries(config)) {
            ini += `[${section}]\n`;
            for (const [key, val] of Object.entries(values)) {
                ini += `${key} = ${val}\n`;
            }
            ini += '\n';
        }

        $configPreview.textContent = ini.trim();
    }

    // ================== PRUEBAS ==================
    function testDatabase() {
        const path = inputs.outputsSqlite3Dbpath.value.trim();
        if (!path) return showAlert('Ruta de BD vacía', 'warning');

        showLoading(true);
        fetch('/api/config/test-db/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({ db_path: path })
        })
        .then(r => r.json())
        .then(data => {
            const status = document.getElementById('dbConnectionStatus');
            if (data.success) {
                status.className = 'status-indicator valid';
                status.innerHTML = '<i class="fas fa-check-circle"></i> Conectado';
                document.getElementById('dbSize').textContent = data.size || 'Desconocido';
                showAlert('Conexión a BD exitosa', 'success');
            } else {
                status.className = 'status-indicator invalid';
                status.innerHTML = '<i class="fas fa-times-circle"></i> Error';
                showAlert('Error BD: ' + data.error, 'danger');
            }
        })
        .finally(() => showLoading(false));
    }

    function testSmtp() {
        const smtp = {
            host: inputs.smtpEmailHost.value,
            port: parseInt(inputs.smtpEmailPort.value),
            ssl: inputs.smtpEmailUseSsl.checked,
            tls: inputs.smtpEmailUseTls.checked,
            user: inputs.smtpEmailHostUser.value,
            password: inputs.smtpEmailHostPassword.value
        };

        showLoading(true);
        fetch('/api/config/test-smtp/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(smtp)
        })
        .then(r => r.json())
        .then(data => {
            const status = document.getElementById('smtpStatus');
            if (data.success) {
                status.className = 'status-indicator valid';
                status.textContent = 'Conectado';
                showAlert('SMTP conectado correctamente', 'success');
            } else {
                status.className = 'status-indicator invalid';
                status.textContent = 'Error';
                showAlert('Error SMTP: ' + data.error, 'danger');
            }
        })
        .finally(() => showLoading(false));
    }

    function sendTestEmail() {
        const email = prompt('Email de destino para prueba:');
        if (!email) return;

        showLoading(true);
        fetch('/api/config/send-test-email/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({ to_email: email })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showAlert('Email de prueba enviado a ' + email, 'success');
            } else {
                showAlert('Error al enviar: ' + data.error, 'danger');
            }
        })
        .finally(() => showLoading(false));
    }

    // ================== IMPORT / EXPORT ==================
    function exportConfig() {
        const config = collectFormData();
        let ini = '';
        for (const [section, values] of Object.entries(config)) {
            ini += `[${section}]\n`;
            for (const [key, val] of Object.entries(values)) {
                ini += `${key} = ${val}\n`;
            }
            ini += '\n';
        }

        const blob = new Blob([ini], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'config.ini';
        a.click();
        URL.revokeObjectURL(url);
    }

    function handleImport(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function (ev) {
            try {
                const text = ev.target.result;
                const parsed = parseIni(text);
                // Sobrescribir currentConfig
                currentConfig = parsed;
                populateForm();
                updatePreview();
                markUnsavedChanges(true);
                showAlert('Configuración importada', 'success');
            } catch (err) {
                showAlert('Error al importar: ' + err.message, 'danger');
            }
        };
        reader.readAsText(file);
    }

    function parseIni(text) {
        const lines = text.split('\n');
        const result = {};
        let currentSection = null;

        for (let line of lines) {
            line = line.trim();
            if (!line || line.startsWith(';') || line.startsWith('#')) continue;
            if (line.startsWith('[') && line.endsWith(']')) {
                currentSection = line.slice(1, -1).trim();
                result[currentSection] = {};
            } else if (currentSection && line.includes('=')) {
                const [key, ...valParts] = line.split('=');
                const value = valParts.join('=').trim();
                result[currentSection][key.trim()] = value;
            }
        }
        return result;
    }

    // ================== RESTAURAR DEFAULTS ==================
    function resetToDefaults() {
        if (!confirm('¿Restaurar valores por defecto?')) return;

        const defaults = {
            inputs: { pdf: 'C:\\Data\\pdf', tablas: 'C:\\Data\\tablas', master: 'C:\\Data\\master' },
            outputs: { logs: 'C:\\Data\\logs', merged: 'C:\\Data\\merged', facturas: 'C:\\Data\\facturas', sqlite3_dbpath: 'C:/data/dentfact.sqlite3' },
            smtp: { email_host: 'smtp.serviapymes.es', email_port: 465, email_use_ssl: 'True', email_use_tls: 'False', email_host_user: 'serviapymes@serviapymes.es', email_host_password: 'assass' },
            default: { gabinete_percentage: '11.5', iva_percentage: '21', irpf_percentage: '15', dd_femision: '05', gastos: '50' }
        };

        currentConfig = { ...defaults };
        populateForm();
        updatePreview();
        markUnsavedChanges(true);
        showAlert('Valores por defecto restaurados', 'info');
    }

    // ================== UTILIDADES ==================
    function markUnsavedChanges(hasChanges) {
        hasUnsavedChanges = hasChanges;
        $unsavedChanges.style.display = hasChanges ? 'block' : 'none';
        $saveBtn.disabled = !hasChanges;
    }

    function updateLastModified(timestamp = null) {
        const date = timestamp ? new Date(timestamp * 1000) : new Date();
        $configLastModified.textContent = date.toLocaleString();
    }

    function showLoading(show) {
        $loadingOverlay.classList.toggle('d-none', !show);
    }

    function showAlert(message, type = 'info') {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        alert.style.top = '20px';
        alert.style.right = '20px';
        alert.style.zIndex = '2000';
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(alert);
        setTimeout(() => alert.remove(), 5000);
    }

    function getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
});