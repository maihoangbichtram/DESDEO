"""Pydantic schemas for the API."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class UserRole(Enum):
    """Enum of user roles."""

    GUEST = "guest"
    DM = "dm"
    ANALYST = "analyst"


class UserPrivileges(Enum):
    """Enum of user privileges."""

    CREATE_PROBLEMS = "Create problems"
    CREATE_USERS = "Create users"
    ACCESS_ALL_PROBLEMS = "Access all problems"
    EDIT_USERS = "Change user privileges, roles, groups, etc."


class ProblemKind(Enum):
    """Enum of problem kinds."""

    CONTINUOUS = "continuous"
    DISCRETE = "discrete"
    MIXED = "mixed"
    BINARY = "binary"


class ObjectiveKind(Enum):
    """Enum of objective kinds."""

    ANALYTICAL = "analytical"
    SIMULATED = "simulated"
    SURROGATE = "surrogate"


class Methods(Enum):
    """Enum of methods."""

    NIMBUS = "nimbus"
    NAUTILUS = "nautilus"
    NAUT_NAVIGATOR = "NAUTILUS navigator"
    NAUTILUSII = "nautilusII"
    RVEA = "RVEA"
    NSGAIII = "NSGAIII"


class MethodProperties(Enum):
    """Enum of method properties."""

    INTERACTIVE = "interactive"
    REFERENCE_POINT = "reference_point"
    CLASSIFICATION = "classification"
    # TODO: Add more properties as needed.


class User(BaseModel):
    """Model for a user. Temporary."""

    username: str = Field(description="Username of the user.")
    index: int | None = Field(
        description=(
            "Index of the user in the database. "
            "Supposed to be automatically generated by the database. "
            "So the programmer should not have to worry about it."
        )
    )
    password_hash: str = Field(description="SHA256 Hash of the user's password.")
    role: UserRole = Field(description="Role of the user.")
    privilages: list[UserPrivileges] = Field(description="List of privileges the user has.")
    user_group: str = Field(description="User group of the user. Used for group decision making.")
    # To allows for User to be initialized from database instead of just dicts.
    model_config = ConfigDict(from_attributes=True)
