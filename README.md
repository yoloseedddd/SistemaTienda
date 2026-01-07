# SistemaTienda (breve guía)

Pasos rápidos para ejecutar localmente:

1. Copia `.env.example` a `.env` y rellena los valores (SECRET_KEY, credenciales DB, etc.).
2. Crea un entorno virtual e instala dependencias:

   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt

3. Asegúrate de que la base de datos exista y el procedimiento almacenado `sp_CompraRapida` esté creado si lo usas.
4. Inicia la app en modo desarrollo (opcional):

   set FLASK_DEBUG=1
   python app.py

5. Recuerda no usar `DEBUG` en producción y usar un usuario de base de datos con privilegios mínimos.

Notas:
- Habilité CSRF con `Flask-WTF`; si usas formularios HTML debes incluir `{{ csrf_token() }}` dentro de cada `<form>`.
- Usa `.env` y no comprometas `SECRET_KEY` ni credenciales en VCS.
