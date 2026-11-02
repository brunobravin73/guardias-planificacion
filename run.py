"""
Script de inicio para la aplicación de Planificación de Guardias Médicas
"""
import uvicorn

if __name__ == "__main__":
    print("Iniciando Sistema de Planificación de Guardias Médicas...")
    print("Accede a la interfaz web en: http://localhost:8000")
    print("Documentación Swagger API en: http://localhost:8000/docs")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
