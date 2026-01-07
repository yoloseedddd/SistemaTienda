"""Pequeño servidor Flask del SistemaTienda.

Mejoras: cargar credenciales desde .env, usar pool, manejo de errores y CSRF.
"""
import os
from dotenv import load_dotenv
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_wtf import CSRFProtect
import mysql.connector
from mysql.connector import pooling, Error as MySQLError

load_dotenv()

app = Flask(__name__)
# SECRET_KEY debe venir de variables de entorno en producción
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')

# Configuración de logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# Habilitar protección CSRF (recuerda incluir {{ csrf_token() }} en tus formularios)
csrf = CSRFProtect(app)

# Configuración de conexión desde variables de entorno
db_config = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASS', ''),
    'database': os.getenv('DB_NAME', 'TiendaMasiva'),
    'raise_on_warnings': True
}

# Crear un pool de conexiones
try:
    pool = pooling.MySQLConnectionPool(pool_name="mypool",
                                       pool_size=int(os.getenv('DB_POOL_SIZE', 5)),
                                       **db_config)
    app.logger.info("MySQL connection pool created (size=%s).", os.getenv('DB_POOL_SIZE', 5))
except Exception as e:
    app.logger.exception("Error creando el pool de MySQL: %s", e)
    pool = None


def get_db_connection():
    """Obtener conexión desde el pool (si existe) o una conexión directa."""
    if pool:
        return pool.get_connection()
    return mysql.connector.connect(**db_config)

# RUTA 1: Pantalla Principal (Dashboard)
@app.route('/')
def index():
    # --- EL GUARDIA DE SEGURIDAD 👮 ---
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))
    # ----------------------------------

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. KPIs
    cursor.execute("SELECT COUNT(*) as total FROM Usuarios")
    t_users = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM Ordenes")
    t_orders = cursor.fetchone()['total']
    
    # 2. Listas para los Selects
    # CÁMBIALA POR ESTA LÍNEA (agregamos password y rol):
    cursor.execute("SELECT id, nombre, password, rol FROM Usuarios")
    users = cursor.fetchall()
    
    cursor.execute("SELECT id, nombre, stock FROM Productos")
    products = cursor.fetchall()
    
    # 3. Tabla de Últimas Ventas
    query_ventas = """
        SELECT o.id, DATE_FORMAT(o.fecha, '%d/%m/%Y') as fecha_bonita, 
               u.nombre as cliente, 
               GROUP_CONCAT(p.nombre SEPARATOR ', ') as lista_productos,
               o.total
        FROM Ordenes o
        JOIN Usuarios u ON o.id_usuario = u.id
        JOIN Detalle_Orden d ON o.id = d.id_orden
        JOIN Productos p ON d.id_producto = p.id
        GROUP BY o.id
        ORDER BY o.fecha DESC LIMIT 10
    """
    cursor.execute(query_ventas)
    ventas = cursor.fetchall()

    # 4. Top 5 Productos
    query_top = """
        SELECT p.nombre, p.imagen_url, SUM(d.cantidad) as total_vendidos, SUM(d.cantidad * d.precio_unitario) as ingresos_generados
        FROM Detalle_Orden d
        JOIN Productos p ON d.id_producto = p.id
        GROUP BY p.id
        ORDER BY total_vendidos DESC LIMIT 5
    """
    cursor.execute(query_top)
    top_products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('index.html', t_users=t_users, t_orders=t_orders, users=users, products=products, ventas=ventas, top_products=top_products)

# RUTA 2: Registrar Nueva Compra (CON VALIDACIÓN DE STOCK 🔒)
@app.route('/comprar', methods=['POST'])
def comprar():
    # 1. Recibimos los datos del formulario
    id_usuario = request.form['id_usuario']
    id_producto = request.form['id_producto']
    cantidad = int(request.form['cantidad']) # Convertimos a número entero
    
    conn = get_db_connection()
    # Usamos dictionary=True para poder llamar a las columnas por su nombre
    cursor = conn.cursor(dictionary=True) 
    
    try:
        # --- PASO 1: EL CANDADO (Verificar Stock) ---
        cursor.execute("SELECT nombre, stock FROM Productos WHERE id = %s", (id_producto,))
        producto = cursor.fetchone()

        if not producto:
            flash('❌ Error: El producto no existe.')
            return redirect(url_for('index'))

        stock_actual = producto['stock']
        nombre_prod = producto['nombre']

        # Aquí ocurre la magia: Comparamos lo que piden vs lo que hay
        if cantidad > stock_actual:
            flash(f'⚠️ ¡Stock Insuficiente! Solo quedan {stock_actual} unidades de "{nombre_prod}".')
            return redirect(url_for('index')) # Detenemos todo y volvemos

        # --- PASO 2: SI HAY STOCK, VENDEMOS ---
        # Si llegó hasta aquí, es porque SÍ alcanza. Ejecutamos la venta.
        cursor.callproc('sp_CompraRapida', [id_usuario, id_producto, cantidad])
        conn.commit()
        
        flash(f'✅ ¡Venta exitosa! Has vendido {cantidad} unidades de {nombre_prod}.')

    except Exception as e:
        conn.rollback() # Si algo falla, deshacemos cambios
        flash(f'Error interno: {str(e)}')
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('index'))

# --- NUEVAS RUTAS PARA LAS VENTANAS ---

# RUTA LOGIN: Validar usuario y contraseña
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario_form = request.form['username']
        password_form = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # BUSCAMOS AL USUARIO EN LA BASE DE DATOS REAL
        cursor.execute("SELECT * FROM Usuarios WHERE nombre = %s AND password = %s", (usuario_form, password_form))
        user_db = cursor.fetchone()
        
        cursor.close()
        conn.close()

        if user_db:
            # ¡Login Exitoso! Guardamos datos en sesión
            session['usuario_logueado'] = user_db['rol']
            session['id_usuario'] = user_db['id']
            session['nombre_usuario'] = user_db['nombre']
            
            # EL SEMÁFORO: ¿A dónde lo mandamos?
            if user_db['rol'] == 'admin':
                return redirect(url_for('index'))  # Al Panel de Control
            else:
                return redirect(url_for('catalogo')) # A la Tienda
        else:
            flash('❌ Usuario o contraseña incorrectos.')
            return redirect(url_for('login'))
            
    return render_template('login.html')

# RUTA NUEVA: Crear Cuenta
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nuevo_usuario = request.form['username']
        nuevo_pass = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificamos si ya existe el nombre
        cursor.execute("SELECT * FROM Usuarios WHERE nombre = %s", (nuevo_usuario,))
        if cursor.fetchone():
            flash('❌ Ese nombre de usuario ya existe. Prueba otro.')
        else:
            # Creamos el usuario nuevo (siempre con rol 'cliente')
            cursor.execute("INSERT INTO Usuarios (nombre, password, rol) VALUES (%s, %s, 'cliente')", 
                           (nuevo_usuario, nuevo_pass))
            conn.commit()
            flash('✅ ¡Cuenta creada con éxito! Ahora puedes ingresar.')
            return redirect(url_for('login'))
        
        conn.close()
            
    return render_template('registro.html')

@app.route('/envios')
def envios():
    return render_template('envios.html')

# RUTA LOGOUT: Salir del sistema
@app.route('/logout')
def logout():
    session.pop('usuario_logueado', None) # Borramos la sesión
    flash('👋 ¡Sesión cerrada correctamente!')
    return redirect(url_for('login'))

# RUTA NUEVA: Ver Recibo de una Orden
@app.route('/recibo/<int:id_orden>')
def recibo(id_orden):
    # Verificamos si está logueado (seguridad)
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Datos de la Cabecera (Orden y Cliente)
    cursor.execute("""
        SELECT o.id, o.fecha, o.total, u.nombre as cliente, u.id as id_usuario
        FROM Ordenes o
        JOIN Usuarios u ON o.id_usuario = u.id
        WHERE o.id = %s
    """, (id_orden,))
    orden = cursor.fetchone()

    # 2. Datos del Detalle (Productos comprados)
    cursor.execute("""
        SELECT p.nombre as producto, d.cantidad, d.precio_unitario
        FROM Detalle_Orden d
        JOIN Productos p ON d.id_producto = p.id
        WHERE d.id_orden = %s
    """, (id_orden,))
    detalles = cursor.fetchall()

    cursor.close()
    conn.close()

    if not orden:
        return "Orden no encontrada", 404

    return render_template('recibo.html', orden=orden, detalles=detalles)

# RUTA MEJORADA: Catálogo con Buscador
@app.route('/catalogo')
def catalogo():
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))
        
    busqueda = request.args.get('q') # Capturamos lo que el usuario escribió
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if busqueda:
        # Si escribió algo, buscamos coincidencias (El % sirve para buscar texto parcial)
        query = "SELECT * FROM Productos WHERE stock > 0 AND nombre LIKE %s ORDER BY precio DESC"
        cursor.execute(query, ('%' + busqueda + '%',))
    else:
        # Si no escribió nada, mostramos todo
        cursor.execute("SELECT * FROM Productos WHERE stock > 0 ORDER BY precio DESC")
    
    productos = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('catalogo.html', productos=productos)

# RUTA PARA QUE EL CLIENTE COMPRE DESDE EL CATÁLOGO
@app.route('/comprar_cliente', methods=['POST'])
def comprar_cliente():
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))

    id_usuario = session['id_usuario'] # Usamos el ID del que está logueado
    id_producto = request.form['id_producto']
    cantidad = int(request.form['cantidad'])

    # Aquí reutilizamos la lógica de compra (podríamos llamar a la función comprar, 
    # pero para simplificar hacemos el proceso rápido):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT stock, nombre FROM Productos WHERE id = %s", (id_producto,))
        prod = cursor.fetchone()
        
        if prod and prod['stock'] >= cantidad:
            cursor.callproc('sp_CompraRapida', [id_usuario, id_producto, cantidad])
            conn.commit()
            flash(f'✅ ¡Compra exitosa! Compraste {cantidad} {prod["nombre"]}.')
        else:
            flash('⚠️ Stock insuficiente.')
    except Exception as e:
        flash('Error en la compra.')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('catalogo'))

# --- LÓGICA DEL CARRITO DE COMPRAS 🛒 ---

# 1. Función para inicializar el carrito si no existe
def asegurar_carrito():
    if 'carrito' not in session:
        session['carrito'] = []

# 2. RUTA: Agregar un producto al carrito (Sin ir a la base de datos todavía)
@app.route('/agregar_carrito', methods=['POST'])
def agregar_carrito():
    asegurar_carrito()
    id_prod = request.form['id_producto']
    cantidad = int(request.form['cantidad'])
    
    # Buscamos los datos del producto para guardarlos en memoria
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Productos WHERE id = %s", (id_prod,))
    prod = cursor.fetchone()
    conn.close()

    if prod:
        # Creamos el item para el carrito
        item = {
            'id': prod['id'],
            'nombre': prod['nombre'],
            'precio': float(prod['precio']),
            'imagen': prod['imagen_url'],
            'cantidad': cantidad,
            'subtotal': float(prod['precio']) * cantidad
        }
        # Guardamos en la lista de sesión (temporal)
        carrito_actual = session['carrito']
        carrito_actual.append(item)
        session['carrito'] = carrito_actual # Actualizamos sesión
        flash(f'🛒 {prod["nombre"]} agregado al carrito.')
    
    return redirect(url_for('catalogo'))

# 2.5. RUTA NUEVA: Procesar el Cupón
@app.route('/aplicar_cupon', methods=['POST'])
def aplicar_cupon():
    codigo = request.form['codigo'].upper().strip() # Convertimos a mayúsculas
    
    if codigo == "PROMO2026":
        session['descuento'] = 0.10 # 10% de descuento
        session['nombre_cupon'] = "PROMO2026"
        flash('✨ ¡Código PROMO2026 aplicado! Tienes 10% de descuento.')
    elif codigo == "VERANO":
        session['descuento'] = 0.20 # 20% de descuento
        session['nombre_cupon'] = "VERANO"
        flash('🌞 ¡Descuento de Verano aplicado! (20%)')
    else:
        flash('❌ Cupón inválido o expirado.')
        # Borramos descuento si se equivocó
        session.pop('descuento', None)
        session.pop('nombre_cupon', None)
        
    return redirect(url_for('ver_carrito'))

# 3. RUTA: Ver la Ventana del Carrito (ahora con cálculo de descuento)
@app.route('/carrito')
def ver_carrito():
    if 'usuario_logueado' not in session: return redirect(url_for('login'))
    asegurar_carrito()
    
    # 1. Calculamos Subtotal
    subtotal = sum(item['subtotal'] for item in session['carrito'])
    
    # 2. Calculamos Descuento (Si existe en sesión)
    porcentaje = session.get('descuento', 0)
    monto_descuento = subtotal * porcentaje
    
    # 3. Total Nuevo
    total_con_descuento = subtotal - monto_descuento
    
    return render_template('carrito.html', 
                         carrito=session['carrito'], 
                         total_productos=total_con_descuento, # OJO: Enviamos el total ya rebajado
                         subtotal_real=subtotal,              # Enviamos el precio original para comparar
                         monto_descuento=monto_descuento,
                         nombre_cupon=session.get('nombre_cupon', ''))

# 4. RUTA: Vaciar Carrito (por si se arrepiente)
@app.route('/limpiar_carrito')
def limpiar_carrito():
    session['carrito'] = []
    return redirect(url_for('catalogo'))

# 5. RUTA FINAL: Confirmar Compra y Generar Boleta Única
@app.route('/confirmar_compra', methods=['POST'])
def confirmar_compra():
    if 'usuario_logueado' not in session: return redirect(url_for('login'))
    
    carrito = session.get('carrito', [])
    if not carrito:
        flash('El carrito está vacío.')
        return redirect(url_for('catalogo'))

    # Datos del formulario de envío
    costo_envio = float(request.form['costo_envio_input'])
    total_final = float(request.form['total_final_input'])
    id_usuario = session['id_usuario']

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # A) Crear la ORDEN PRINCIPAL (Cabecera)
        cursor.execute("INSERT INTO Ordenes (id_usuario, fecha, total) VALUES (%s, NOW(), %s)", 
                       (id_usuario, total_final))
        id_orden = cursor.lastrowid # ¡Obtenemos el ID de la boleta nueva!

        # B) Guardar cada producto en DETALLE_ORDEN
        for item in carrito:
            cursor.execute("""
                INSERT INTO Detalle_Orden (id_orden, id_producto, cantidad, precio_unitario)
                VALUES (%s, %s, %s, %s)
            """, (id_orden, item['id'], item['cantidad'], item['precio']))
            
            # C) Descontar Stock
            cursor.execute("UPDATE Productos SET stock = stock - %s WHERE id = %s", 
                           (item['cantidad'], item['id']))

        conn.commit()
        
        # Limpiamos el carrito porque ya compró
        session['carrito'] = []
        
        # ¡Redirigimos directo a la Boleta para imprimir!
        return redirect(url_for('recibo', id_orden=id_orden))

    except Exception as e:
        conn.rollback()
        # ESTA LÍNEA ES NUEVA: Imprimirá el error en la ventana negra
        print(f"\n🛑 ERROR GRAVE EN LA COMPRA: {e}\n")
        flash(f'Error al procesar compra: {str(e)}')
        return redirect(url_for('ver_carrito'))
    finally:
        conn.close()

# RUTA: PERFIL DE USUARIO E HISTORIAL
@app.route('/perfil')
def perfil():
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))
        
    id_usuario = session['id_usuario']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Datos del Usuario
    cursor.execute("SELECT * FROM Usuarios WHERE id = %s", (id_usuario,))
    usuario = cursor.fetchone()
    
    # 2. Historial de Compras (Ordenes)
    # Traemos la orden y cuántos productos tenía esa orden
    query = """
        SELECT o.id, o.fecha, o.total, COUNT(d.id) as cantidad_total
        FROM Ordenes o
        LEFT JOIN Detalle_Orden d ON o.id = d.id_orden
        WHERE o.id_usuario = %s
        GROUP BY o.id
        ORDER BY o.fecha DESC
    """
    cursor.execute(query, (id_usuario,))
    historial = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('perfil.html', usuario=usuario, historial=historial)
 # --- ZONA ADMINISTRATIVA (CRUD) ---

# 1. VER LISTA DE PRODUCTOS (SOLO ADMIN)
@app.route('/admin/productos')
def admin_productos():
    # Candado de seguridad: Solo el admin pasa
    if 'usuario_logueado' not in session or session['usuario_logueado'] != 'admin':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Productos ORDER BY id DESC")
    productos = cursor.fetchall()
    conn.close()
    
    return render_template('admin_productos.html', productos=productos)

# 2. GUARDAR NUEVO PRODUCTO
@app.route('/admin/agregar', methods=['POST'])
def agregar_producto():
    if session.get('usuario_logueado') != 'admin': return redirect(url_for('login'))
    
    nombre = request.form['nombre']
    precio = request.form['precio']
    stock = request.form['stock']
    imagen = request.form['imagen']
    
    # Si no pone foto, usamos una por defecto
    if not imagen: imagen = "https://via.placeholder.com/300"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO Productos (nombre, precio, stock, imagen_url) VALUES (%s, %s, %s, %s)",
                   (nombre, precio, stock, imagen))
    conn.commit()
    conn.close()
    
    flash('✅ Producto agregado correctamente.')
    return redirect(url_for('admin_productos'))

# 3. ELIMINAR PRODUCTO
@app.route('/admin/eliminar/<int:id>')
def eliminar_producto(id):
    if session.get('usuario_logueado') != 'admin': return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Productos WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    
    flash('🗑️ Producto eliminado.')
    return redirect(url_for('admin_productos'))

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0')