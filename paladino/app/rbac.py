"""
Lightweight RBAC (Role-Based Access Control) for internal Paladino instances.

Designed for single-user or small team internal deployments.
Stores roles and permissions in Neo4j for easy management.

Usage:
    from paladino.app.rbac import get_user_permissions
    
    # Check permission in endpoint
    @app.get("/sensitive")
    async def sensitive_endpoint(user: User = Depends(get_current_user)):
        if not user.has_permission("company:delete"):
            raise HTTPException(403, "Permission denied")
        ...
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from paladino.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Permission Definitions
# ─────────────────────────────────────────────────────────────────────────────

class Permission(str, Enum):
    """
    All available permissions in the system.
    
    Format: resource:action
    Resources: company, tender, project, person, user, admin
    Actions: read, write, delete, admin
    """
    # Company permissions
    COMPANY_READ = "company:read"
    COMPANY_WRITE = "company:write"
    COMPANY_DELETE = "company:delete"
    
    # Tender permissions
    TENDER_READ = "tender:read"
    TENDER_WRITE = "tender:write"
    TENDER_DELETE = "tender:delete"
    
    # Project permissions
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    PROJECT_DELETE = "project:delete"
    
    # Person permissions
    PERSON_READ = "person:read"
    PERSON_WRITE = "person:write"
    PERSON_DELETE = "person:delete"
    
    # User management
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    
    # Admin operations
    ADMIN_ETL = "admin:etl"  # Run ETL pipelines
    ADMIN_SCHEMA = "admin:schema"  # Modify schema
    ADMIN_AUDIT = "admin:audit"  # View audit logs
    ADMIN_BULK_IMPORT = "admin:bulk_import"  # Bulk data import
    ADMIN_EXPORT = "admin:export"  # Export data
    
    # Search and analytics
    SEARCH = "search"  # Use search endpoint
    LINEAGE = "lineage"  # View data lineage
    EXPORT = "export"  # Export query results


# ─────────────────────────────────────────────────────────────────────────────
# Role Definitions
# ─────────────────────────────────────────────────────────────────────────────

class RoleType(str, Enum):
    """Built-in system roles."""
    ADMIN = "admin"  # Full access
    ANALYST = "analyst"  # Read + analyze, no deletes
    DATA_ENGINEER = "data_engineer"  # ETL + write, no admin
    VIEWER = "viewer"  # Read-only


# Role to permissions mapping
ROLE_PERMISSIONS = {
    RoleType.ADMIN: {
        Permission.COMPANY_READ,
        Permission.COMPANY_WRITE,
        Permission.COMPANY_DELETE,
        Permission.TENDER_READ,
        Permission.TENDER_WRITE,
        Permission.TENDER_DELETE,
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.PROJECT_DELETE,
        Permission.PERSON_READ,
        Permission.PERSON_WRITE,
        Permission.PERSON_DELETE,
        Permission.USER_READ,
        Permission.USER_WRITE,
        Permission.USER_DELETE,
        Permission.ADMIN_ETL,
        Permission.ADMIN_SCHEMA,
        Permission.ADMIN_AUDIT,
        Permission.ADMIN_BULK_IMPORT,
        Permission.ADMIN_EXPORT,
        Permission.SEARCH,
        Permission.LINEAGE,
        Permission.EXPORT,
    },
    
    RoleType.ANALYST: {
        Permission.COMPANY_READ,
        Permission.TENDER_READ,
        Permission.PROJECT_READ,
        Permission.PERSON_READ,
        Permission.SEARCH,
        Permission.LINEAGE,
        Permission.EXPORT,
        Permission.USER_READ,
    },
    
    RoleType.DATA_ENGINEER: {
        Permission.COMPANY_READ,
        Permission.COMPANY_WRITE,
        Permission.TENDER_READ,
        Permission.TENDER_WRITE,
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.PERSON_READ,
        Permission.PERSON_WRITE,
        Permission.ADMIN_ETL,
        Permission.ADMIN_BULK_IMPORT,
        Permission.SEARCH,
        Permission.LINEAGE,
    },
    
    RoleType.VIEWER: {
        Permission.COMPANY_READ,
        Permission.TENDER_READ,
        Permission.PROJECT_READ,
        Permission.PERSON_READ,
        Permission.SEARCH,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# User Model
# ─────────────────────────────────────────────────────────────────────────────

class User(BaseModel):
    """User model with RBAC support."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: str | None = None
    role: RoleType = RoleType.VIEWER
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = None
    is_active: bool = True
    
    # API key for this user
    api_key: str = Field(default_factory=lambda: hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:32])
    api_key_hash: str = Field(default="")
    
    def __init__(self, **data):
        super().__init__(**data)
        # Hash API key on creation
        if not self.api_key_hash and self.api_key:
            self.api_key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()
    
    def has_permission(self, permission: Permission | str) -> bool:
        """Check if user has a specific permission."""
        if not self.is_active:
            return False
        
        perm = permission if isinstance(permission, Permission) else Permission(permission)
        return perm in ROLE_PERMISSIONS.get(self.role, set())
    
    def has_any_permission(self, permissions: list[Permission | str]) -> bool:
        """Check if user has at least one of the given permissions."""
        return any(self.has_permission(p) for p in permissions)
    
    def has_all_permissions(self, permissions: list[Permission | str]) -> bool:
        """Check if user has all of the given permissions."""
        return all(self.has_permission(p) for p in permissions)
    
    def can_access_endpoint(self, method: str, path: str) -> bool:
        """
        Check if user can access an endpoint based on method and path.
        
        Simple path-based routing:
        - GET → READ permission
        - POST/PUT → WRITE permission
        - DELETE → DELETE permission
        """
        # Extract resource from path
        path_parts = path.strip("/").split("/")
        if not path_parts or path_parts[0] in ["health", "ready", "live", "docs", "openapi.json"]:
            return True  # Public endpoints
        
        resource = path_parts[0]
        
        # Map path to permission
        method_to_action = {
            "GET": "read",
            "POST": "write" if "ingest" in path or "import" in path else "read",
            "PUT": "write",
            "PATCH": "write",
            "DELETE": "delete",
        }
        
        action = method_to_action.get(method.upper(), "read")
        
        # Special cases
        if resource == "audit":
            return self.has_permission(Permission.ADMIN_AUDIT)
        if resource in ["ingest", "bulk"]:
            return self.has_permission(Permission.ADMIN_BULK_IMPORT)
        if resource == "export":
            return self.has_permission(Permission.EXPORT)
        if resource == "search":
            return self.has_permission(Permission.SEARCH)
        if resource == "lineage":
            return self.has_permission(Permission.LINEAGE)
        
        # Standard resource permissions
        try:
            perm = Permission(f"{resource}:{action}")
            return self.has_permission(perm)
        except ValueError:
            # Unknown resource - default to read
            return self.has_permission(Permission.COMPANY_READ)
    
    def get_permissions(self) -> set[Permission]:
        """Get all permissions for this user's role."""
        return ROLE_PERMISSIONS.get(self.role, set())
    
    def to_dict(self, include_api_key: bool = False) -> dict:
        """Convert to dictionary (safe for API responses)."""
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
            "permissions": [p.value for p in self.get_permissions()],
        }
        if include_api_key:
            data["api_key"] = self.api_key
        return data


# ─────────────────────────────────────────────────────────────────────────────
# User Store (In-Memory for Prototype)
# ─────────────────────────────────────────────────────────────────────────────

class UserStore:
    """
    Simple in-memory user store for prototype.
    
    For production, replace with Neo4j-backed store.
    """
    
    def __init__(self):
        self._users: dict[str, User] = {}
        self._api_key_index: dict[str, str] = {}  # api_key_hash -> user_id
        self._init_default_user()
    
    def _init_default_user(self):
        """Create default admin user from environment."""
        admin_key = settings.api_keys.split(",")[0] if settings.api_keys else None
        
        if admin_key:
            admin = User(
                username="admin",
                email="admin@paladino.local",
                role=RoleType.ADMIN,
                api_key=admin_key,
            )
            self.add(admin)
    
    def add(self, user: User) -> None:
        """Add or update a user."""
        self._users[user.id] = user
        self._api_key_index[user.api_key_hash] = user.id
    
    def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        return self._users.get(user_id)
    
    def get_by_api_key(self, api_key: str) -> User | None:
        """Authenticate user by API key."""
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        user_id = self._api_key_index.get(api_key_hash)
        if user_id:
            user = self._users.get(user_id)
            if user and user.is_active:
                user.last_login = datetime.utcnow()
                return user
        return None
    
    def get_by_username(self, username: str) -> User | None:
        """Get user by username."""
        for user in self._users.values():
            if user.username == username:
                return user
        return None
    
    def list_users(self) -> list[User]:
        """List all users."""
        return list(self._users.values())
    
    def delete(self, user_id: str) -> bool:
        """Delete a user."""
        user = self._users.get(user_id)
        if user:
            if user.api_key_hash in self._api_key_index:
                del self._api_key_index[user.api_key_hash]
            del self._users[user_id]
            return True
        return False
    
    def update_role(self, user_id: str, role: RoleType) -> bool:
        """Update user's role."""
        user = self._users.get(user_id)
        if user:
            user.role = role
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Global User Store Instance
# ─────────────────────────────────────────────────────────────────────────────

user_store = UserStore()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Dependencies
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    """
    Get current authenticated user from API key.
    
    Usage:
        @app.get("/protected")
        async def protected(user: User = Depends(get_current_user)):
            return {"user": user.username}
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = user_store.get_by_api_key(creds.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def require_permission(permission: Permission | str):
    """
    Dependency factory to require specific permission.
    
    Usage:
        @app.delete("/companies/{id}")
        async def delete_company(
            id: str,
            user: User = Depends(require_permission(Permission.COMPANY_DELETE))
        ):
            ...
    """
    async def permission_checker(user: User = Depends(get_current_user)) -> User:
        perm = permission if isinstance(permission, Permission) else Permission(permission)
        if not user.has_permission(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {perm.value}",
            )
        return user
    
    return permission_checker


def require_role(role: RoleType | str):
    """
    Dependency factory to require specific role.
    
    Usage:
        @app.post("/admin/reset")
        async def admin_reset(
            user: User = Depends(require_role(RoleType.ADMIN))
        ):
            ...
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        required_role = role if isinstance(role, RoleType) else RoleType(role)
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {required_role.value}",
            )
        return user
    
    return role_checker
