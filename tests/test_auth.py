"""Tests for auth module."""

import pytest
from flask import session, abort
from app.auth import login_user, logout_user, current_user_id, current_user_role, require_auth, require_roles


class TestAuthFunctions:
    """Test cases for auth utility functions."""
    
    def test_login_user(self, app):
        """Test logging in a user."""
        with app.test_request_context():
            login_user(1, "admin")
            assert session["user_id"] == 1
            assert session["role"] == "admin"
    
    def test_logout_user(self, app):
        """Test logging out a user."""
        with app.test_request_context():
            login_user(1, "admin")
            assert session["user_id"] == 1
            
            logout_user()
            assert "user_id" not in session
            assert "role" not in session
    
    def test_current_user_id(self, app):
        """Test getting current user ID."""
        with app.test_request_context():
            assert current_user_id() is None
            
            login_user(42, "admin")
            assert current_user_id() == 42
    
    def test_current_user_role(self, app):
        """Test getting current user role."""
        with app.test_request_context():
            assert current_user_role() is None
            
            login_user(1, "technician")
            assert current_user_role() == "technician"
    
    def test_current_user_when_logged_out(self, app):
        """Test current user info when not logged in."""
        with app.test_request_context():
            assert current_user_id() is None
            assert current_user_role() is None


class TestRequireAuth:
    """Test cases for require_auth decorator."""
    
    def test_require_auth_allows_logged_in_user(self, app):
        """Test that require_auth allows logged in users."""
        @require_auth
        def protected_view():
            return "Success"
        
        with app.test_request_context():
            login_user(1, "admin")
            result = protected_view()
            assert result == "Success"
    
    def test_require_auth_denies_anonymous_user(self, app):
        """Test that require_auth denies anonymous users."""
        @require_auth
        def protected_view():
            return "Success"
        
        with app.test_request_context():
            with pytest.raises(Exception):  # werkzeug abort
                protected_view()
    
    def test_require_auth_preserves_function_name(self, app):
        """Test that decorator preserves function metadata."""
        @require_auth
        def my_view():
            """My docstring"""
            return "test"
        
        assert my_view.__name__ == "my_view"
        assert "docstring" in my_view.__doc__.lower()


class TestRequireRoles:
    """Test cases for require_roles decorator."""
    
    def test_require_roles_allows_authorized_role(self, app):
        """Test that require_roles allows authorized roles."""
        @require_roles("admin", "cs")
        def admin_view():
            return "Admin Success"
        
        with app.test_request_context():
            login_user(1, "admin")
            result = admin_view()
            assert result == "Admin Success"
    
    def test_require_roles_denies_unauthorized_role(self, app):
        """Test that require_roles denies unauthorized roles."""
        @require_roles("admin")
        def admin_only_view():
            return "Admin Success"
        
        with app.test_request_context():
            login_user(1, "technician")
            with pytest.raises(Exception):  # werkzeug abort
                admin_only_view()
    
    def test_require_roles_denies_anonymous_user(self, app):
        """Test that require_roles denies anonymous users."""
        @require_roles("admin")
        def admin_view():
            return "Admin Success"
        
        with app.test_request_context():
            with pytest.raises(Exception):  # werkzeug abort
                admin_view()
    
    def test_require_roles_with_multiple_allowed_roles(self, app):
        """Test require_roles with multiple allowed roles."""
        @require_roles("admin", "cs", "technician")
        def all_users_view():
            return f"Welcome {current_user_role()}"
        
        with app.test_request_context():
            login_user(1, "technician")
            result = all_users_view()
            assert "technician" in result
    
    def test_require_roles_preserves_function_metadata(self, app):
        """Test that decorator preserves function metadata."""
        @require_roles("admin")
        def protected():
            """Protected function"""
            pass
        
        assert protected.__name__ == "protected"
