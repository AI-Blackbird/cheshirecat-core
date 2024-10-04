import json
from typing import List, Dict
import redis

from cat.db.crud_source import CrudSource
from cat.db.models import Setting
from cat.utils import singleton


@singleton
class Redis(CrudSource):
    host: str
    port: int
    db: int
    password: str | None

    def __init__(self):
        self.redis = redis.Redis(
            host=self.host, port=self.port, db=self.db, password=self.password, encoding="utf-8", decode_responses=True
        )

    def __get(self, key: str) -> List[Dict]:
        value = self.redis.get(key)
        if not value:
            return []

        if isinstance(value, (bytes, str)):
            return json.loads(value)
        else:
            raise ValueError(f"Unexpected type for Redis value: {type(value)}")

    def __set(self, key: str, value: List[Dict]):
        self.redis.set(key, json.dumps(value))

    def get_settings(self, search: str = "", *args, **kwargs) -> List[Dict]:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        return [setting for setting in settings if search in setting["name"]]

    def get_settings_by_category(self, category: str, *args, **kwargs) -> List[Dict]:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        return [setting for setting in settings if setting["category"] == category]

    def create_setting(self, payload: Setting, *args, **kwargs) -> Dict:
        chatbot_id = kwargs.get("chatbot_id")
        self.__set(chatbot_id, [payload.model_dump()])

        # retrieve the record we just created
        result = self.get_setting_by_id(payload.setting_id)
        return result

    def get_setting_by_name(self, name: str, *args, **kwargs) -> Dict | None:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        settings = [setting for setting in settings if setting["name"] == name]
        if not settings:
            return None

        return settings[0]

    def get_setting_by_id(self, setting_id: str, *args, **kwargs) -> Dict | None:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        settings = [setting for setting in settings if setting["setting_id"] == setting_id]
        if not settings:
            return None

        return settings[0]

    def delete_setting_by_id(self, setting_id: str, *args, **kwargs) -> None:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        if not settings:
            return

        settings = [setting for setting in settings if setting["setting_id"] != setting_id]
        self.__set(chatbot_id, settings)

    def delete_settings_by_category(self, category: str, *args, **kwargs) -> None:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        if not settings:
            return

        settings = [setting for setting in settings if setting["category"] != category]
        self.__set(chatbot_id, settings)

    def update_setting_by_id(self, payload: Setting, *args, **kwargs) -> Dict | None:
        chatbot_id = kwargs.get("chatbot_id")
        settings = self.__get(chatbot_id)

        if not settings:
            return None

        for setting in settings:
            if setting["setting_id"] == payload.setting_id:
                setting.update(payload.model_dump())

        self.__set(chatbot_id, settings)
        return self.get_setting_by_id(payload.setting_id)

    def upsert_setting_by_name(self, payload: Setting, *args, **kwargs) -> Dict | None:
        chatbot_id = kwargs.get("chatbot_id")
        old_setting = self.get_setting_by_name(payload.name, chatbot_id=chatbot_id)

        if not old_setting:
            self.create_setting(payload, chatbot_id=chatbot_id)
        else:
            settings = self.__get(chatbot_id)
            for setting in settings:
                if setting["name"] == payload.name:
                    setting.update(payload.model_dump())

            self.__set(chatbot_id, settings)

        return self.get_setting_by_name(payload.name, chatbot_id=chatbot_id)