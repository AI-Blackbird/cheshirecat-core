from typing import Dict, List
from uuid import uuid4

from cat.auth.permissions import get_full_permissions, get_base_permissions
from cat.auth.auth_utils import hash_password
from cat.db.models import Setting
from cat.factory.crud_source import get_db


def get_settings(search: str = "") -> List[Dict]:
    settings = get_db().get_settings(search)
    # Workaround: do not expose users in the settings list
    settings = [s for s in settings if s["name"] != "users"]
    return settings


def get_settings_by_category(category: str) -> List[Dict]:
    return get_db().get_settings_by_category(category)


def create_setting(payload: Setting) -> Dict:
    # Missing fields (setting_id, updated_at) are filled automatically by pydantic
    return get_db().create_setting(payload)


def get_setting_by_name(name: str) -> Dict | None:
    return get_db().get_setting_by_name(name)


def get_setting_by_id(setting_id: str) -> Dict | None:
    return get_db().get_setting_by_name(setting_id)


def delete_setting_by_id(setting_id: str) -> None:
    get_db().delete_setting_by_id(setting_id)


def delete_settings_by_category(category: str) -> None:
    get_db().delete_settings_by_category(category)


def update_setting_by_id(payload: Setting) -> Dict:
    return get_db().update_setting_by_id(payload)


def upsert_setting_by_name(payload: Setting) -> Setting:
    return get_db().upsert_setting_by_name(payload)


# We store users in a setting and when there will be a graph db in the cat, we will store them there.
# P.S.: I'm not proud of this.
def get_users() -> Dict[str, Dict]:
    users = get_setting_by_name("users")
    if not users:
        # create admin user and an ordinary user
        admin_id = str(uuid4())
        user_id = str(uuid4())

        update_users({
            admin_id: {
                "id": admin_id,
                "username": "admin",
                "password": hash_password("admin"),
                # admin has all permissions
                "permissions": get_full_permissions()
            },
            user_id: {
                "id": user_id,
                "username": "user",
                "password": hash_password("user"),
                # user has minor permissions
                "permissions": get_base_permissions()
            }
        })
    return get_setting_by_name("users")["value"]

def update_users(users: Dict[str, Dict]) -> Setting:
    updated_users = Setting(
        name="users",
        value=users
    )
    return upsert_setting_by_name(updated_users)