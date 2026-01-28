from app import app, db, Usuario

def resetear_admin():
    print("🔄 Conectando a la base de datos...")
    
    with app.app_context():
        # 1. Buscar si existe el usuario
        user = Usuario.query.filter_by(username='admin').first()
        
        if user:
            print("⚠️ El usuario 'admin' ya existía. Actualizando contraseña...")
            user.set_password('admin123')
            db.session.commit()
            print("✅ Contraseña restablecida a: admin123")
        else:
            print("🆕 El usuario no existía. Creándolo ahora...")
            nuevo_user = Usuario(username='admin')
            nuevo_user.set_password('admin123')
            db.session.add(nuevo_user)
            db.session.commit()
            print("✅ Usuario 'admin' creado exitosamente.")

if __name__ == "__main__":
    resetear_admin()