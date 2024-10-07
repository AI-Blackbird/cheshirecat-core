from typing import Dict, List
from tinydb import TinyDB, Query
from uuid import uuid4

from cat.auth.permissions import get_full_permissions, get_base_permissions
from cat.auth.auth_utils import hash_password
from cat.db.crud_source import CrudSource
from cat.db.models import Setting


class DatabaseCrudSource(CrudSource):
    file: str

    def __init__(self):
        self.db = TinyDB(self.file)

    def get_settings(self, search: str = "", *args, **kwargs) -> List[Dict]:
        query = Query()
        return self.db.search(query.name.matches(search))

    def get_settings_by_category(self, category: str, *args, **kwargs) -> List[Dict]:
        query = Query()
        return self.db.search(query.category == category)

    def create_setting(self, payload: Setting, *args, **kwargs) -> Dict:
        # Missing fields (setting_id, updated_at) are filled automatically by pydantic
        self.db.insert(payload.model_dump())

        # retrieve the record we just created
        return self.get_setting_by_id(payload.setting_id)

    def get_setting_by_name(self, name: str, *args, **kwargs) -> Dict | None:
        query = Query()
        result = self.db.search(query.name == name)
        if len(result) > 0:
            return result[0]
        return None

    def get_setting_by_id(self, setting_id: str, *args, **kwargs) -> Dict | None:
        query = Query()
        result = self.db.search(query.setting_id == setting_id)
        if len(result) > 0:
            return result[0]
        return None

    def delete_setting_by_id(self, setting_id: str, *args, **kwargs) -> None:
        query = Query()
        self.db.remove(query.setting_id == setting_id)

    def delete_settings_by_category(self, category: str, *args, **kwargs) -> None:
        query = Query()
        self.db.remove(query.category == category)

    def update_setting_by_id(self, payload: Setting, *args, **kwargs) -> Dict:
        query = Query()
        self.db.update(payload, query.setting_id == payload.setting_id)

        return self.get_setting_by_id(payload.setting_id)

    def upsert_setting_by_name(self, payload: Setting, *args, **kwargs) -> Dict | None:
        old_setting = self.get_setting_by_name(payload.name)

        if not old_setting:
            self.create_setting(payload)
        else:
            query = Query()
            self.db.update(payload, query.name == payload.name)

        return self.get_setting_by_name(payload.name)

    # We store users in a setting and when there will be a graph db in the cat, we will store them there.
    # P.S.: I'm not proud of this.
    def get_users(self, *args, **kwargs) -> Dict[str, Dict]:
        users = self.get_setting_by_name("users", *args, **kwargs)
        if not users:
            # create admin user and an ordinary user
            admin_id = str(uuid4())
            user_id = str(uuid4())

            self.update_users({
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
        return self.get_setting_by_name("users", *args, **kwargs)["value"]

    def update_users(self, users: Dict[str, Dict], *args, **kwargs) -> Dict | None:
        updated_users = Setting(name="users", value=users)
        return self.upsert_setting_by_name(updated_users, *args, **kwargs)

    def get_auth_setting_by_name(self, name: str) -> Dict | None:
        return self.get_setting_by_name(name)

    def get_auth_settings_by_category(self, category: str) -> List[Dict]:
        return self.get_settings_by_category(category)

    def upsert_auth_setting_by_name(self, payload: Setting) -> Dict | None:
        return self.upsert_setting_by_name(payload)
