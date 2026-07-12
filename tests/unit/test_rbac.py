"""
Unit tests for RBAC (Role-Based Access Control).
"""

import pytest
from paladino.app.rbac import (
    User,
    RoleType,
    Permission,
    ROLE_PERMISSIONS,
    UserStore,
    user_store,
    get_current_user,
    require_permission,
    require_role,
)
from fastapi import HTTPException


class TestPermission:
    """Test Permission enum."""
    
    def test_permission_values(self):
        """Test permission string values."""
        assert Permission.COMPANY_READ.value == "company:read"
        assert Permission.COMPANY_WRITE.value == "company:write"
        assert Permission.COMPANY_DELETE.value == "company:delete"
        assert Permission.ADMIN_ETL.value == "admin:etl"
    
    def test_permission_from_string(self):
        """Test creating permission from string."""
        perm = Permission("company:read")
        assert perm == Permission.COMPANY_READ


class TestRolePermissions:
    """Test role to permission mappings."""
    
    def test_admin_has_all_permissions(self):
        """Admin role should have all permissions."""
        admin_perms = ROLE_PERMISSIONS[RoleType.ADMIN]
        
        # Should have key permissions
        assert Permission.COMPANY_READ in admin_perms
        assert Permission.COMPANY_DELETE in admin_perms
        assert Permission.ADMIN_ETL in admin_perms
        assert Permission.ADMIN_AUDIT in admin_perms
    
    def test_analyst_read_only(self):
        """Analyst role should have read permissions, no writes."""
        analyst_perms = ROLE_PERMISSIONS[RoleType.ANALYST]
        
        assert Permission.COMPANY_READ in analyst_perms
        assert Permission.TENDER_READ in analyst_perms
        assert Permission.COMPANY_WRITE not in analyst_perms
        assert Permission.COMPANY_DELETE not in analyst_perms
        assert Permission.ADMIN_ETL not in analyst_perms
    
    def test_viewer_limited(self):
        """Viewer role should have minimal permissions."""
        viewer_perms = ROLE_PERMISSIONS[RoleType.VIEWER]
        
        assert Permission.COMPANY_READ in viewer_perms
        assert Permission.SEARCH in viewer_perms
        assert Permission.COMPANY_WRITE not in viewer_perms
        assert Permission.EXPORT not in viewer_perms


class TestUser:
    """Test User model."""
    
    def test_user_creation(self):
        """Test creating a user."""
        user = User(username="testuser", role=RoleType.ANALYST)
        
        assert user.username == "testuser"
        assert user.role == RoleType.ANALYST
        assert user.is_active is True
        assert user.api_key is not None
        assert len(user.api_key) == 32
    
    def test_user_has_permission(self):
        """Test permission checking."""
        admin = User(username="admin", role=RoleType.ADMIN)
        viewer = User(username="viewer", role=RoleType.VIEWER)
        
        assert admin.has_permission(Permission.COMPANY_DELETE) is True
        assert viewer.has_permission(Permission.COMPANY_DELETE) is False
    
    def test_user_has_any_permission(self):
        """Test checking for any of multiple permissions."""
        user = User(username="analyst", role=RoleType.ANALYST)
        
        assert user.has_any_permission([
            Permission.COMPANY_READ,
            Permission.COMPANY_DELETE,
        ]) is True  # Has READ
        
        assert user.has_any_permission([
            Permission.COMPANY_DELETE,
            Permission.ADMIN_ETL,
        ]) is False  # Has neither
    
    def test_user_has_all_permissions(self):
        """Test checking for all permissions."""
        user = User(username="analyst", role=RoleType.ANALYST)
        
        assert user.has_all_permissions([
            Permission.COMPANY_READ,
            Permission.TENDER_READ,
        ]) is True
        
        assert user.has_all_permissions([
            Permission.COMPANY_READ,
            Permission.COMPANY_WRITE,
        ]) is False  # Missing WRITE
    
    def test_inactive_user_denied(self):
        """Test that inactive users are denied all permissions."""
        user = User(username="inactive", role=RoleType.ADMIN, is_active=False)
        
        assert user.has_permission(Permission.COMPANY_READ) is False
    
    def test_can_access_endpoint(self):
        """Test endpoint access checking."""
        admin = User(username="admin", role=RoleType.ADMIN)
        viewer = User(username="viewer", role=RoleType.VIEWER)
        
        # Admin can access everything
        assert admin.can_access_endpoint("GET", "/companies") is True
        assert admin.can_access_endpoint("DELETE", "/companies/123") is True
        
        # Viewer can read but analyst can export (viewer doesn't have export)
        assert viewer.can_access_endpoint("GET", "/companies") is True
        # Viewer can't access bulk import
        assert viewer.can_access_endpoint("POST", "/ingest/bulk") is False
    
    def test_get_permissions(self):
        """Test getting all user permissions."""
        user = User(username="test", role=RoleType.VIEWER)
        perms = user.get_permissions()
        
        assert isinstance(perms, set)
        assert len(perms) > 0
        assert Permission.COMPANY_READ in perms
    
    def test_to_dict(self):
        """Test user serialization."""
        user = User(username="test", role=RoleType.ANALYST)
        data = user.to_dict()
        
        assert "id" in data
        assert "username" in data
        assert "role" in data
        assert "permissions" in data
        assert "api_key" not in data  # Should not include API key by default
        
        # With API key
        data_with_key = user.to_dict(include_api_key=True)
        assert "api_key" in data_with_key


class TestUserStore:
    """Test UserStore."""
    
    def test_add_user(self):
        """Test adding a user."""
        store = UserStore()
        user = User(username="newuser", role=RoleType.VIEWER)
        
        store.add(user)
        
        assert store.get_by_id(user.id) is user
        assert store.get_by_username("newuser") is user
    
    def test_get_by_api_key(self):
        """Test authentication by API key."""
        store = UserStore()
        user = User(username="apiuser", role=RoleType.ANALYST)
        
        store.add(user)
        
        # Authenticate with API key
        authenticated = store.get_by_api_key(user.api_key)
        assert authenticated is user
        assert authenticated.last_login is not None
    
    def test_get_by_invalid_api_key(self):
        """Test authentication with invalid key."""
        store = UserStore()
        
        result = store.get_by_api_key("invalid_key")
        assert result is None
    
    def test_delete_user(self):
        """Test deleting a user."""
        store = UserStore()
        user = User(username="tempuser", role=RoleType.VIEWER)
        
        store.add(user)
        assert store.get_by_id(user.id) is user
        
        store.delete(user.id)
        assert store.get_by_id(user.id) is None
    
    def test_update_role(self):
        """Test updating user role."""
        store = UserStore()
        user = User(username="roleuser", role=RoleType.VIEWER)
        
        store.add(user)
        store.update_role(user.id, RoleType.ADMIN)
        
        updated = store.get_by_id(user.id)
        assert updated.role == RoleType.ADMIN
    
    def test_inactive_user_auth_fails(self):
        """Test that inactive users cannot authenticate."""
        store = UserStore()
        user = User(username="inactive", role=RoleType.ADMIN, is_active=False)
        
        store.add(user)
        
        result = store.get_by_api_key(user.api_key)
        assert result is None


class TestRBACDependencies:
    """Test FastAPI dependencies."""
    
    @pytest.mark.asyncio
    async def test_require_permission(self):
        """Test require_permission dependency."""
        from fastapi import Depends
        
        # Create checker for a permission ANALYST has
        checker = require_permission(Permission.COMPANY_READ)
        
        # Create user with permission
        user = User(username="analyst", role=RoleType.ANALYST)
        
        # Should not raise
        result = await checker(user=user)
        assert result is user
        
        # Create user without this specific permission
        viewer = User(username="viewer", role=RoleType.VIEWER)
        
        # Viewer has COMPANY_READ, so let's test with EXPORT which they don't have
        checker_export = require_permission(Permission.EXPORT)
        
        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            await checker_export(user=viewer)
        
        assert exc_info.value.status_code == 403
    
    @pytest.mark.asyncio
    async def test_require_role(self):
        """Test require_role dependency."""
        checker = require_role(RoleType.ADMIN)
        
        # Admin user - should pass
        admin = User(username="admin", role=RoleType.ADMIN)
        result = await checker(user=admin)
        assert result is admin
        
        # Non-admin - should fail
        viewer = User(username="viewer", role=RoleType.VIEWER)
        
        with pytest.raises(HTTPException) as exc_info:
            await checker(user=viewer)
        
        assert exc_info.value.status_code == 403
