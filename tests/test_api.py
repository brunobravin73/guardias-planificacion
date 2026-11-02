"""
Pruebas de integración de la API FastAPI y endpoints del planificador
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    print("\n[OK] API Health check passed.")

def test_public_config_endpoint():
    response = client.get("/api/public-config")
    assert response.status_code == 200
    data = response.json()
    assert "supabase_enabled" in data
    assert "supabase_url" in data
    assert "supabase_key" in data
    print("\n[OK] API Public Config endpoint passed.")

def test_auth_confirm_redirect():
    response = client.get("/auth/confirm?token_hash=abc123&type=email", follow_redirects=False)
    assert response.status_code == 307
    assert "token_hash=abc123" in response.headers.get("location", "")
    print("\n[OK] Auth confirm redirect passed.")

def test_countries_endpoint():
    response = client.get("/api/countries")
    assert response.status_code == 200
    countries = response.json()
    assert len(countries) >= 5
    assert any(c["code"] == "AR" for c in countries)
    print("\n[OK] API Countries endpoint passed.")

def test_month_info_endpoint():
    response = client.get("/api/month-info?year=2026&month=10&country_code=AR")
    assert response.status_code == 200
    data = response.json()
    assert data["total_days"] == 31
    assert len(data["days"]) == 31
    assert data["thursdays_count"] >= 4
    print("\n[OK] API Month Info endpoint passed.")

def test_demo_data_endpoint():
    response = client.get("/api/demo-data?country_code=AR")
    assert response.status_code == 200
    data = response.json()
    assert len(data["doctors"]) == 6
    assert "days_config" in data
    assert "restrictions" in data
    print("\n[OK] API Demo Data endpoint passed.")

def test_solve_endpoint_with_demo():
    # Obtener demo data y resolver directamente
    demo_res = client.get("/api/demo-data?country_code=AR")
    demo_data = demo_res.json()
    
    solve_res = client.post("/api/solve", json=demo_data)
    assert solve_res.status_code == 200
    result = solve_res.json()
    assert result["success"] is True
    assert len(result["schedule"]) > 0
    assert len(result["stats"]) == 6
    for stat in result["stats"]:
        assert stat["total_shifts"] == 7
        assert stat["consecutive_violations"] == 0
    print("\n[OK] API Solve endpoint passed with exact 7 shifts & zero consecutive days.")

def test_static_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "MedGuard" in response.text
    print("\n[OK] Static UI index.html served correctly.")

if __name__ == "__main__":
    test_health_check()
    test_public_config_endpoint()
    test_auth_confirm_redirect()
    test_countries_endpoint()
    test_month_info_endpoint()
    test_demo_data_endpoint()
    test_solve_endpoint_with_demo()
    test_static_index()
    print("\n[OK] Todos los tests de la API pasaron con exito.")
