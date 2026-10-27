from __future__ import annotations

from conftest import ADMIN_PASSWORD, CSRF, create_user, login, new_client


def test_health_and_unauthenticated(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/jobs").status_code == 401


def test_no_register_endpoint(client):
    assert client.post("/api/auth/register", json={"username": "x", "password": "y"}).status_code in (404, 405)


def test_admin_login_sets_secure_cookie(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["username"] == "admin"


def test_wrong_password_and_lockout(client):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "bad-password"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 429


def test_unknown_user_same_error(client):
    r = client.post("/api/auth/login", json={"username": "nobody", "password": "whatever"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Usuario o contraseña incorrectos"


def test_csrf_header_required(app):
    with new_client(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}, headers={"X-Requested-With": ""})
        assert r.status_code == 403


def test_logout(admin):
    admin.post("/api/auth/logout")
    assert admin.get("/api/auth/me").status_code == 401


def test_created_user_must_change_password(admin, app):
    r = admin.post("/api/users", json={"username": "maria", "role": "user"})
    assert r.status_code == 201
    temp = r.json()["temporary_password"]
    assert temp and len(temp) >= 16
    with new_client(app) as c:
        me = login(c, "maria", temp)
        assert me["must_change_password"] is True
        assert c.get("/api/nodes").status_code == 403
        r = c.post("/api/auth/change-password", json={"current_password": temp, "new_password": "short"})
        assert r.status_code == 400
        r = c.post("/api/auth/change-password", json={"current_password": temp, "new_password": "Clave-Nueva-2026"})
        assert r.status_code == 200
        assert c.get("/api/nodes").status_code == 200


def test_non_admin_cannot_manage_users(admin, app):
    c = create_user(admin, app, "pepe")
    assert c.get("/api/users").status_code == 403
    assert c.post("/api/users", json={"username": "hack"}).status_code == 403


def test_deactivate_invalidates_session(admin, app):
    c = create_user(admin, app, "luis")
    uid = c.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/login", json={"username": "luis", "password": "New-Password-456"})
    assert r.status_code == 401


def test_reset_password(admin, app):
    c = create_user(admin, app, "ana")
    uid = c.get("/api/auth/me").json()["id"]
    temp = admin.post(f"/api/users/{uid}/reset-password").json()["temporary_password"]
    assert c.get("/api/auth/me").status_code == 401
    with new_client(app) as c2:
        assert login(c2, "ana", temp)["must_change_password"] is True


def test_admin_protections(admin):
    me = admin.get("/api/auth/me").json()
    assert admin.delete(f"/api/users/{me['id']}").status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert admin.post("/api/users", json={"username": "admin"}).status_code == 409
    assert admin.post("/api/users", json={"username": "bad name!"}).status_code == 400


def test_delete_user(admin, app):
    c = create_user(admin, app, "temporal")
    uid = c.get("/api/auth/me").json()["id"]
    assert admin.delete(f"/api/users/{uid}").status_code == 204
    assert all(u["username"] != "temporal" for u in admin.get("/api/users").json())


def test_tampered_cookie_rejected(app):
    with new_client(app) as c:
        c.cookies.set("snackdrop_session", "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.")
        assert c.get("/api/auth/me").status_code == 401
    assert CSRF
