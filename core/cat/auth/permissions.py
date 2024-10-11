from typing import Dict, List

from cat.utils import BaseModelDict, Enum


class AuthResource(Enum):
    CRUD = "CRUD"
    STATUS = "STATUS"
    MEMORY = "MEMORY"
    CONVERSATION = "CONVERSATION"
    SETTINGS = "SETTINGS"
    LLM = "LLM"
    EMBEDDER = "EMBEDDER"
    AUTH_HANDLER = "AUTH_HANDLER"
    USERS = "USERS"
    UPLOAD = "UPLOAD"
    PLUGINS = "PLUGINS"
    STATIC = "STATIC"
    ADMIN = "ADMIN"


class AuthPermission(Enum):
    WRITE = "WRITE"
    EDIT = "EDIT"
    LIST = "LIST"
    READ = "READ"
    DELETE = "DELETE"


def get_full_permissions() -> Dict[str, List[str]]:
    """
    Returns all available resources and permissions.
    """
    return {str(res): [str(p) for p in AuthPermission] for res in AuthResource}


def get_base_permissions() -> Dict[str, List[str]]:
    """
    Returns the default permissions for new users (chat only!).
    """
    return {
        "STATUS": ["READ"],
        "MEMORY": ["READ", "LIST"],
        "CONVERSATION": ["WRITE", "EDIT", "LIST", "READ", "DELETE"],
        "STATIC": ["READ"],
    }


class AuthUserInfo(BaseModelDict):
    """
    Class to represent token content after the token has been decoded.
    Will be created by AuthHandler(s) to standardize their output.
    Core will use this object to retrieve or create a StrayCat (session)
    """

    id: str
    name: str

    # permissions
    permissions: Dict[str, List[str]] = get_base_permissions()

    # only put in here what you are comfortable to pass plugins:
    # - profile data
    # - custom attributes
    # - roles
    extra: BaseModelDict = {}

