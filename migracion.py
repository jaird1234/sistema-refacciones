import pandas as pd
from sqlalchemy import create_engine
import uuid

# --- CONFIGURACIÓN ---
# Pega aquí tu URL de Supabase otra vez
DB_STRING = "postgresql://postgres.xlufakzwiyecloegabke:F0GAkPZJcZbKB7ZW@aws-1-us-east-2.pooler.supabase.com:6543/postgres"
ARCHIVO_CSV = "Copia de Stock en tiempo real - Stock Actual.csv"

def limpiar_dinero(valor):
    """Limpia $ y , de los precios"""
    if pd.isna(valor): return 0.0
    val_str = str(valor).replace('$', '').replace(',', '').strip()
    try:
        return float(val_str)
    except:
        return 0.0

def generar_codigo_faltante(contador):
    return f"GEN-{str(contador).zfill(4)}"

def encontrar_columna(df, palabras_clave, indice_por_defecto):
    """Busca una columna que contenga alguna de las palabras clave. Si no, usa el índice."""
    cols_mayus = [c.upper() for c in df.columns]
    
    for palabra in palabras_clave:
        for col_real in df.columns:
            if palabra in col_real.upper():
                return col_real
    
    # Si no encuentra por nombre, devuelve por posición (0, 1, 2...)
    try:
        col_encontrada = df.columns[indice_por_defecto]
        print(f"⚠️ Aviso: No encontré '{palabras_clave[0]}', usaré la columna '{col_encontrada}'")
        return col_encontrada
    except:
        return None

def migrar_stock_avanzado():
    print("1. Leyendo archivo CSV...")
    try:
        # Intentamos leer con UTF-8 primero (estándar moderno)
        df = pd.read_csv(ARCHIVO_CSV, encoding='utf-8')
    except:
        try:
            # Si falla, probamos Latin-1 (común en Excel en español)
            df = pd.read_csv(ARCHIVO_CSV, encoding='latin-1')
        except Exception as e:
            print("❌ Error crítico leyendo el archivo.")
            print(e)
            return

    print("2. Procesando datos...")
    df.columns = df.columns.str.strip() # Quitar espacios en blanco de los títulos
    
    # --- DETECCIÓN INTELIGENTE DE COLUMNAS ---
    # Buscamos las columnas aunque estén mal escritas
    col_codigo = encontrar_columna(df, ['CODIGO', 'CÓDIGO', 'CODE'], 0)
    col_desc = encontrar_columna(df, ['DESC', 'NAME', 'NOMBRE', 'PRODUCTO'], 1)
    col_cant = encontrar_columna(df, ['CANT', 'STOCK', 'QTY'], 2)
    col_precio = encontrar_columna(df, ['PRECIO', 'PRICE', 'COSTO'], 3)
    # Buscamos precio final o usamos el mismo precio si no existe
    col_precio_final = encontrar_columna(df, ['FINAL', 'TOTAL', 'MXN'], -1)

    print(f"   Columnas detectadas: {col_codigo} | {col_desc} | {col_cant} | {col_precio}")

    # 1. Generar códigos faltantes
    mask_sin_codigo = df[col_codigo].isna() | (df[col_codigo].astype(str).str.strip() == '')
    contador_gen = 1
    for index, row in df[mask_sin_codigo].iterrows():
        df.at[index, col_codigo] = generar_codigo_faltante(contador_gen)
        contador_gen += 1
    
    if contador_gen > 1:
        print(f"   -> Se generaron códigos para {contador_gen - 1} productos.")

    # 2. Preparar datos finales
    datos_finales = pd.DataFrame()
    datos_finales['codigo'] = df[col_codigo]
    datos_finales['descripcion'] = df[col_desc] # Aquí es donde fallaba antes
    datos_finales['cantidad_actual'] = df[col_cant].fillna(0).astype(int)
    
    # 3. Precios
    datos_finales['precio_usd'] = df[col_precio].apply(limpiar_dinero)
    
    if col_precio_final:
        datos_finales['precio_mxn'] = df[col_precio_final].apply(limpiar_dinero)
    else:
        datos_finales['precio_mxn'] = 0.0

    print(f"   -> {len(datos_finales)} productos listos.")

    print("3. Subiendo a Supabase...")
    engine = create_engine(DB_STRING)
    
    try:
        datos_finales.to_sql('productos', engine, if_exists='append', index=False, method='multi')
        print("\n✅ ¡MIGRACIÓN EXITOSA!")
        print("Corre a ver tu tabla en Supabase.")
    except Exception as e:
        print("\n❌ Error al subir:")
        print(e)
        print("Posible causa: Códigos duplicados. Borra la tabla en Supabase y vuelve a crearla si es necesario.")

if __name__ == "__main__":
    migrar_stock_avanzado()