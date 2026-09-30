(function () {
    'use strict';

    var form = document.getElementById('loginForm');
    if (!form) return;

    var overlay = document.getElementById('loadingOverlay');
    var btn = document.getElementById('loginBtn');
    var username = document.getElementById('username');
    var password = document.getElementById('password');
    var toggle = document.getElementById('togglePassword');

    function setError(input, message) {
        var box = document.getElementById(input.id + 'Feedback');
        if (box) box.textContent = message;
        input.classList.toggle('is-invalid', !!message);
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
    }

    // Mostrar / ocultar contraseña
    toggle.addEventListener('click', function () {
        var show = password.type === 'password';
        password.type = show ? 'text' : 'password';
        toggle.setAttribute('aria-pressed', String(show));
        toggle.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
        toggle.querySelector('i').className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
        password.focus();
    });

    // Limpiar el error al escribir
    [username, password].forEach(function (el) {
        el.addEventListener('input', function () { setError(el, ''); });
    });

    // Validación básica en cliente (el servidor valida igualmente)
    form.addEventListener('submit', function (e) {
        var ok = true;
        if (!username.value.trim()) { setError(username, 'Introduce tu usuario o email.'); ok = false; }
        if (!password.value) { setError(password, 'Introduce tu contraseña.'); ok = false; }
        if (!ok) {
            e.preventDefault();
            (username.value.trim() ? password : username).focus();
            return;
        }
        btn.disabled = true;
        overlay.classList.add('show');
    });

    // Al volver con el botón "atrás" el formulario no debe quedar bloqueado
    window.addEventListener('pageshow', function (ev) {
        if (ev.persisted) {
            btn.disabled = false;
            overlay.classList.remove('show');
        }
    });
})();
