
import pandas as pd
import io
from sqlalchemy import text
from flask import send_file
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import extract
from sqlalchemy import func
from datetime import datetime


app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave_secreta_super_segura'
# TU BASE DE DATOS:
app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://postgres.xlufakzwiyecloegabke:F0GAkPZJcZbKB7ZW@aws-1-us-east-2.pooler.supabase.com:6543/postgres"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELOS ---
class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(200))
    # NUEVO CAMPO
    is_approved = db.Column(db.Boolean, default=False) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String, unique=True)
    descripcion = db.Column(db.String)
    cantidad_actual = db.Column(db.Integer)
    precio_usd = db.Column(db.Float)
    precio_mxn = db.Column(db.Float)
    stock_minimo = db.Column(db.Integer, default=5)

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String, nullable=False)
    telefono = db.Column(db.String)
    email = db.Column(db.String)
    direccion = db.Column(db.String)

class Venta(db.Model):
    __tablename__ = 'ventas'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    total = db.Column(db.Float)
    tipo_entrega = db.Column(db.String)
    direccion_envio = db.Column(db.String)
    cliente = db.relationship('Cliente')
    
    # --- ESTA LÍNEA ES LA MAGIA QUE PERMITE BORRAR ---
    detalles = db.relationship('DetalleVenta', backref='venta', cascade="all, delete-orphan")

class DetalleVenta(db.Model):
    __tablename__ = 'detalle_ventas'
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('ventas.id'))
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'))
    cantidad = db.Column(db.Integer)
    precio_unitario = db.Column(db.Float)
    producto = db.relationship('Producto')

@login_manager.user_loader
def load_user(user_id): return Usuario.query.get(int(user_id))

# --- RUTAS ---

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    # --- 1. DATOS GENERALES (KPIs) ---
    hoy = datetime.now().date()
    inicio_mes = hoy.replace(day=1)

    ventas_hoy = db.session.query(func.sum(Venta.total)).filter(func.date(Venta.fecha) == hoy).scalar() or 0
    ventas_mes = db.session.query(func.sum(Venta.total)).filter(Venta.fecha >= inicio_mes).scalar() or 0
    total_clientes = Cliente.query.count()
    productos_bajos = Producto.query.filter(Producto.cantidad_actual <= Producto.stock_minimo).count()

    # --- 2. LÓGICA DE RANKING INTELIGENTE ---
    ranking_bruto = db.session.query(
        Producto,
        func.sum(DetalleVenta.cantidad).label('total_vendido')
    ).join(DetalleVenta).group_by(Producto.id).all()

    ranking_procesado = []

    for producto, total_vendido in ranking_bruto:
        if not total_vendido: total_vendido = 0
            
        cantidad_normalizada = float(total_vendido)
        tipo_venta = "Unidad"
        
        # Obtenemos textos en mayúsculas para comparar fácil
        codigo = producto.codigo.upper()
        desc = producto.descripcion.upper()

        # REGLA 1: Empaques XE (Prioridad Alta: Juegos de 18)
        # Si dice XE, se divide entre 18 (aunque diga Empaque, entra aquí primero)
        if "XE" in codigo or "XE" in desc:
            cantidad_normalizada = total_vendido / 18
            tipo_venta = "Juego (18 pzs)"
            
        # REGLA 2: Pares, Kits o CUALQUIER OTRO EMPAQUE (Juegos de 2)
        # Agregamos 'or "EMPAQUE" in desc' para que todos los demás empaques sean pares
        elif ("PAR" in codigo or "JGO" in codigo or "2PZ" in codigo or 
              "PAR" in desc or "EMPAQUE" in desc):
            cantidad_normalizada = total_vendido / 2
            tipo_venta = "Par / Kit (2 pzs)"

        if cantidad_normalizada > 0:
            ranking_procesado.append({
                'producto': producto,
                'cantidad_ranking': cantidad_normalizada,
                'tipo': tipo_venta
            })

    # Ordenamos Top 5
    ranking_top = sorted(ranking_procesado, key=lambda x: x['cantidad_ranking'], reverse=True)[:5]

    # --- 3. USUARIOS PENDIENTES ---
    usuarios_pendientes = []
    if current_user.username == 'admin': 
        usuarios_pendientes = Usuario.query.filter_by(is_approved=False).all()

    return render_template('dashboard.html', 
                           ventas_hoy=ventas_hoy,
                           ventas_mes=ventas_mes,
                           total_clientes=total_clientes,
                           productos_bajos=productos_bajos,
                           ranking_top=ranking_top,
                           pendientes=usuarios_pendientes)




@app.route('/inventario', methods=['GET', 'POST'])
@login_required
def inventario():
    if request.method == 'POST':
        try:
            nuevo = Producto(
                codigo=request.form['codigo'],
                descripcion=request.form['descripcion'],
                cantidad_actual=int(request.form['cantidad']),
                stock_minimo=int(request.form.get('stock_minimo', 5)),
                precio_mxn=float(request.form['precio_mxn']),
                precio_usd=float(request.form.get('precio_usd', 0))
            )
            db.session.add(nuevo)
            db.session.commit()
            flash('Producto agregado', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        return redirect(url_for('inventario'))

    busqueda = request.args.get('buscar', '')
    orden = request.args.get('orden', 'stock_asc')
    query = Producto.query
    if busqueda:
        filtro = f"%{busqueda}%"
        query = query.filter((Producto.descripcion.ilike(filtro)) | (Producto.codigo.ilike(filtro)))
    
    if orden == 'stock_asc': query = query.order_by(Producto.cantidad_actual.asc())
    elif orden == 'stock_desc': query = query.order_by(Producto.cantidad_actual.desc())
    elif orden == 'precio_alto': query = query.order_by(Producto.precio_mxn.desc())
    else: query = query.order_by(Producto.descripcion.asc())
    
    return render_template('inventario.html', productos=query.all())

@app.route('/editar_producto/<int:id>', methods=['POST'])
@login_required
def editar_producto(id):
    p = Producto.query.get_or_404(id)
    p.descripcion = request.form['descripcion']
    p.cantidad_actual = int(request.form['cantidad'])
    p.stock_minimo = int(request.form.get('stock_minimo', 5))
    p.precio_mxn = float(request.form['precio'])
    db.session.commit()
    flash('Producto actualizado', 'success')
    return redirect(url_for('inventario'))

# --- CLIENTES (Nuevo: Editar y Borrar) ---
@app.route('/clientes', methods=['GET', 'POST'])
@login_required
def clientes():
    if request.method == 'POST':
        nuevo = Cliente(
            nombre=request.form['nombre'],
            telefono=request.form['telefono'],
            email=request.form['email'],
            direccion=request.form['direccion']
        )
        db.session.add(nuevo)
        db.session.commit()
        flash('Cliente registrado', 'success')
        return redirect(url_for('clientes'))
    
    return render_template('clientes.html', clientes=Cliente.query.order_by(Cliente.nombre).all())

@app.route('/editar_cliente/<int:id>', methods=['POST'])
@login_required
def editar_cliente(id):
    c = Cliente.query.get_or_404(id)
    c.nombre = request.form['nombre']
    c.telefono = request.form['telefono']
    c.email = request.form['email']
    c.direccion = request.form['direccion']
    db.session.commit()
    flash('Cliente actualizado', 'success')
    return redirect(url_for('clientes'))

@app.route('/borrar_cliente/<int:id>')
@login_required
def borrar_cliente(id):
    if id == 1: # Protección para el cliente por defecto
        flash('No puedes borrar al Público General', 'danger')
        return redirect(url_for('clientes'))
    
    c = Cliente.query.get_or_404(id)
    # Pasar ventas a cliente genérico antes de borrar
    ventas = Venta.query.filter_by(cliente_id=id).all()
    for v in ventas:
        v.cliente_id = 1
    
    db.session.delete(c)
    db.session.commit()
    flash('Cliente eliminado correctamente', 'success')
    return redirect(url_for('clientes'))

# --- VENTAS (Nuevo: Select2 y Borrar Venta con retorno de stock) ---
@app.route('/nueva-venta', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    if request.method == 'POST':
        data = request.json
        
        # Obtenemos dirección: Si es paquetería usamos la del form, si no, vacía o la del cliente
        direccion = data.get('direccion_envio', '')
        
        nueva_venta = Venta(
            cliente_id=data['cliente_id'], 
            total=data['total'],
            tipo_entrega=data['tipo_entrega'],
            direccion_envio=direccion
        )
        db.session.add(nueva_venta)
        db.session.flush()
        
        for item in data['productos']:
            detalle = DetalleVenta(
                venta_id=nueva_venta.id,
                producto_id=item['id'],
                cantidad=item['cantidad'],
                precio_unitario=item['precio']
            )
            db.session.add(detalle)
            prod = Producto.query.get(item['id'])
            prod.cantidad_actual -= int(item['cantidad'])
            
        db.session.commit()
        return jsonify({'status': 'success', 'venta_id': nueva_venta.id})

    clientes = Cliente.query.all()
    productos = Producto.query.filter(Producto.cantidad_actual > 0).all()
    return render_template('nueva_venta.html', clientes=clientes, productos=productos)

@app.route('/historial-ventas')
@login_required
def historial_ventas():
    ventas = Venta.query.order_by(Venta.fecha.desc()).limit(100).all()
    return render_template('ventas.html', ventas=ventas)





@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = Usuario.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # --- VALIDACIÓN DE APROBACIÓN ---
            if not user.is_approved:
                flash('🔒 Tu cuenta está pendiente de aprobación por el Administrador.', 'warning')
                return redirect(url_for('login'))
            # --------------------------------
            
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('⚠️ Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')


@app.route('/borrar_venta/<int:id>')
@login_required
def borrar_venta(id):
    try:
        venta = Venta.query.get_or_404(id)
        
        # 1. DEVOLVER STOCK AL INVENTARIO
        # (Si no hacemos esto, borramos la venta pero el stock se pierde)
        for detalle in venta.detalles:
            producto = Producto.query.get(detalle.producto_id)
            if producto:
                producto.cantidad_actual += detalle.cantidad
        
        # 2. BORRAR LA VENTA
        # Gracias al 'cascade' de arriba, los detalles se borran solos
        db.session.delete(venta)
        db.session.commit()
        
        flash('✅ Venta eliminada y productos devueltos al inventario.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al borrar: {str(e)}', 'error')
        
    return redirect(url_for('historial_ventas'))

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/exportar_inventario')
@login_required
def exportar_inventario():
    # 1. Obtener todos los productos de la base de datos
    productos = Producto.query.order_by(Producto.descripcion).all()
    
    # 2. Convertirlos a una lista de diccionarios (formato para Excel)
    data = []
    for p in productos:
        data.append({
            'Código': p.codigo,
            'Descripción': p.descripcion,
            'Stock Actual': p.cantidad_actual,
            'Stock Mínimo': p.stock_minimo,
            'Precio MXN': p.precio_mxn,
            'Precio USD': p.precio_usd,
            'Valor Total Inventario': p.cantidad_actual * p.precio_mxn # Cálculo útil
        })
    
    # 3. Crear el DataFrame de Pandas
    df = pd.DataFrame(data)
    
    # 4. Crear un archivo Excel en memoria (RAM)
    output = io.BytesIO()
    # Usamos el motor 'openpyxl' para escribir el Excel
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventario')
        
        # (Opcional) Ajustar ancho de columnas automáticamente para que se vea bonito
        worksheet = writer.sheets['Inventario']
        for column in df:
            column_width = max(df[column].astype(str).map(len).max(), len(column))
            col_idx = df.columns.get_loc(column)
            worksheet.column_dimensions[chr(65 + col_idx)].width = column_width + 2
            
    output.seek(0)
    
    # 5. Enviar el archivo al navegador para descargar
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='Reporte_Inventario.xlsx'
    )
@app.route('/registrar', methods=['GET', 'POST'])
def registrar():
    # Si ya estás logueado, te manda al dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 1. Verificar si el usuario ya existe
        if Usuario.query.filter_by(username=username).first():
            flash('⚠️ Ese usuario ya existe.', 'danger')
            return redirect(url_for('registrar'))
        
        # 2. Crear nuevo usuario (Pendiente de aprobación)
        nuevo_usuario = Usuario(username=username, is_approved=False)
        nuevo_usuario.set_password(password)
        
        db.session.add(nuevo_usuario)
        db.session.commit()
        
        flash('✅ Cuenta creada. Espera a que un Administrador te apruebe.', 'info')
        return redirect(url_for('login'))
        
    return render_template('registro.html')

@app.route('/nota_remision/<int:id>')
@login_required
def ver_nota(id):
    venta = Venta.query.get_or_404(id)
    return render_template('nota.html', venta=venta)
@app.route('/aprobar_usuario/<int:id>')
@login_required
def aprobar_usuario(id):
    if current_user.username != 'admin': # Seguridad extra
        return redirect(url_for('dashboard'))
        
    user = Usuario.query.get_or_404(id)
    user.is_approved = True
    db.session.commit()
    flash(f'✅ Usuario {user.username} aprobado con éxito.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/rechazar_usuario/<int:id>')
@login_required
def rechazar_usuario(id):
    if current_user.username != 'admin':
        return redirect(url_for('dashboard'))

    user = Usuario.query.get_or_404(id)
    db.session.delete(user) # Lo borramos de la base de datos
    db.session.commit()
    flash(f'🚫 Solicitud de {user.username} rechazada y eliminada.', 'warning')
    return redirect(url_for('dashboard'))
# Ejemplo rápido para app.py
@app.route('/eliminar_producto/<int:id>')
@login_required
def eliminar_producto(id):
    producto = Producto.query.get_or_404(id)
    db.session.delete(producto)
    db.session.commit()
    flash('Producto eliminado correctamente', 'success')
    return redirect(url_for('inventario'))
# Agrega esto en tu app.py junto a las otras rutas
@app.route('/etiquetas')
@login_required
def etiquetas():
    # Traemos todos los clientes para el buscador
    clientes = Cliente.query.all() 
    return render_template('etiquetas.html', clientes=clientes)







if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)