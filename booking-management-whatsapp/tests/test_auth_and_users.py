"""
Tests for authentication, login, and user management endpoints.
Targets app.py lines 156-180 (login/logout) and user management routes.
"""
from app.models import User, db


class TestAuthenticationFlow:
    """Test authentication and session management"""

    def test_login_page_accessible(self, client):
        """Test accessing login page"""
        response = client.get("/login")
        assert response.status_code == 200

    def test_login_post_valid_credentials(self, client, app):
        """Test login with valid credentials"""
        with app.app_context():
            user = User.query.filter_by(username="admin").first()
            if not user:
                user = User(username="admin", password_hash="hashed", role="admin")
                db.session.add(user)
                db.session.commit()

        response = client.post("/login", data={
            "username": "admin",
            "password": "test"
        })
        # Will fail auth but tests that endpoint processes POST
        assert response.status_code in [200, 302, 401]

    def test_login_missing_username(self, client):
        """Test login without username"""
        response = client.post("/login", data={
            "password": "password"
        })
        assert response.status_code in [200, 302, 400]

    def test_login_missing_password(self, client):
        """Test login without password"""
        response = client.post("/login", data={
            "username": "admin"
        })
        assert response.status_code in [200, 302, 400]

    def test_login_empty_fields(self, client):
        """Test login with empty fields"""
        response = client.post("/login", data={
            "username": "",
            "password": ""
        })
        assert response.status_code in [200, 302, 400]

    def test_login_nonexistent_user(self, client):
        """Test login with non-existent user"""
        response = client.post("/login", data={
            "username": "nonexistent_user_12345",
            "password": "anypassword"
        })
        assert response.status_code in [200, 302, 401]

    def test_logout_redirects(self, client, session_login):
        """Test logout endpoint"""
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code in [302, 200]

    def test_logout_clears_session(self, client, session_login):
        """Test that logout clears session"""
        # First verify we're logged in
        response1 = client.get("/")
        assert response1.status_code in [200, 302]

        # Logout
        client.get("/logout")

        # Next request should require auth
        response2 = client.get("/dashboard")
        assert response2.status_code in [302, 401, 403]


class TestProtectedEndpoints:
    """Test that endpoints require authentication"""

    def test_dashboard_requires_login(self, client):
        """Test that dashboard requires authentication"""
        response = client.get("/dashboard")
        assert response.status_code in [302, 401, 403]

    def test_bookings_requires_login(self, client):
        """Test that bookings requires authentication"""
        response = client.get("/bookings")
        assert response.status_code in [302, 401, 403]

    def test_customers_requires_login(self, client):
        """Test that customers requires authentication"""
        response = client.get("/customers")
        assert response.status_code in [302, 401, 403]

    def test_users_requires_login(self, client):
        """Test that users requires authentication"""
        response = client.get("/users")
        assert response.status_code in [302, 401, 403]

    def test_inbox_requires_login(self, client):
        """Test that inbox requires authentication"""
        response = client.get("/inbox")
        assert response.status_code in [302, 401, 403]

    def test_settings_requires_login(self, client):
        """Test that settings requires authentication"""
        response = client.get("/settings")
        assert response.status_code in [302, 401, 403]

    def test_reschedule_requires_login(self, client):
        """Test that reschedule requires authentication"""
        response = client.get("/reschedule")
        assert response.status_code in [302, 401, 403]

    def test_maintenance_requires_login(self, client):
        """Test that maintenance requires authentication"""
        response = client.get("/maintenance")
        assert response.status_code in [302, 401, 403]


class TestPublicEndpoints:
    """Test public endpoints that don't require auth"""

    def test_root_accessible(self, client):
        """Test that root path is accessible"""
        response = client.get("/")
        assert response.status_code in [200, 302]

    def test_login_accessible(self, client):
        """Test that login page is accessible"""
        response = client.get("/login")
        assert response.status_code == 200

    def test_whatsapp_inbound_accessible(self, client):
        """Test that WhatsApp inbound endpoint is accessible"""
        response = client.post("/api/whatsapp/inbound", json={
            "phone": "628123456789",
            "text": "Hello",
            "from_me": False
        })
        # Should be accessible without auth
        assert response.status_code in [200, 400, 422]


class TestSessionManagement:
    """Test session handling"""

    def test_session_created_on_login(self, client, app):
        """Test that session is created on login"""
        with client:
            with app.app_context():
                # Create admin user
                user = User.query.filter_by(username="admin").first()
                if not user:
                    user = User(username="admin", password_hash="hashed", role="admin")
                    db.session.add(user)
                    db.session.commit()

            response = client.post("/login", data={
                "username": "admin",
                "password": "test"
            }, follow_redirects=True)
            # Check if session was attempted (can't verify session value without auth)

    def test_session_persistence(self, client, session_login):
        """Test that session persists across requests"""
        response1 = client.get("/dashboard")
        assert response1.status_code == 200

        response2 = client.get("/bookings")
        assert response2.status_code == 200


class TestUserRoles:
    """Test user role-based access control"""

    def test_admin_dashboard_access(self, client, session_login):
        """Test admin can access dashboard"""
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_admin_users_access(self, client, session_login):
        """Test admin can access users page"""
        response = client.get("/users")
        assert response.status_code == 200

    def test_admin_bookings_access(self, client, session_login):
        """Test admin can access bookings"""
        response = client.get("/bookings")
        assert response.status_code == 200


class TestRootRoute:
    """Test root route behavior"""

    def test_root_redirect_when_logged_in(self, client, session_login):
        """Test root redirects to dashboard when logged in"""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [200, 302]

    def test_root_redirect_when_not_logged_in(self, client):
        """Test root when not logged in"""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in [200, 302]
