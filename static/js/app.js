// Funciones mínimas para mejorar UX en el envío del formulario
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form[onsubmit]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var btn = form.querySelector('button[type=submit]');
      if (!btn) return;
      // Añadir spinner si no existe
      if (!btn.querySelector('.spinner-border')) {
        var span = document.createElement('span');
        span.className = 'spinner-border spinner-border-sm';
        span.setAttribute('role','status');
        span.setAttribute('aria-hidden','true');
        btn.appendChild(span);
      }
      btn.setAttribute('disabled','true');
    });
  });
});
