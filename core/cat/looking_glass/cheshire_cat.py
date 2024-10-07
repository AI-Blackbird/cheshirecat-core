from typing import List, Dict
from typing_extensions import Protocol

from cat.factory.auth_handler import get_auth_handler_from_name
from cat.factory.custom_auth_handler import CoreAuthHandler
import cat.factory.auth_handler as auth_handlers
from cat.db import crud, models
from cat.looking_glass.white_rabbit import WhiteRabbit
from cat.log import log
from cat.mad_hatter.mad_hatter import MadHatter
from cat.rabbit_hole import RabbitHole
from cat.utils import singleton

class Procedure(Protocol):
    name: str
    procedure_type: str  # "tool" or "form"

    # {
    #   "description": [],
    #   "start_examples": [],
    # }
    triggers_map: Dict[str, List[str]]


# main class
@singleton
class CheshireCat:
    """The Cheshire Cat.

    This is the main class that manages everything. It is a singleton, so there is only one instance of it.
    """

    def __init__(self):
        """Cat initialization.

        At init time the Cat executes the bootstrap.
        """

        # bootstrap the Cat! ^._.^

        # instantiate MadHatter (loads all plugins' hooks and tools)
        self.core_auth_handler = None
        self.custom_auth_handler = None

        self.mad_hatter = MadHatter()

        # load AuthHandler
        self.load_auth()

        # Start scheduling system
        self.white_rabbit = WhiteRabbit()

        # allows plugins to do something before cat components are loaded
        self.mad_hatter.execute_hook("before_cat_bootstrap", cat=self)

        # Rabbit Hole Instance
        self.rabbit_hole = RabbitHole(self)  # :(

        # allows plugins to do something after the cat bootstrap is complete
        self.mad_hatter.execute_hook("after_cat_bootstrap", cat=self)

    def load_auth(self):
        # Custom auth_handler # TODOAUTH: change the name to custom_auth
        selected_auth_handler = crud.get_auth_setting_by_name(name="auth_handler_selected")

        # if no auth_handler is saved, use default one and save to db
        if selected_auth_handler is None:
            # create the auth settings
            crud.upsert_auth_setting_by_name(
                models.Setting(
                    name="CoreOnlyAuthConfig", category="auth_handler_factory", value={}
                )
            )
            crud.upsert_auth_setting_by_name(
                models.Setting(
                    name="auth_handler_selected",
                    category="auth_handler_factory",
                    value={"name": "CoreOnlyAuthConfig"},
                )
            )

            # reload from db
            selected_auth_handler = crud.get_auth_setting_by_name(
                name="auth_handler_selected"
            )

        # get AuthHandler factory class
        selected_auth_handler_class = selected_auth_handler["value"]["name"]
        FactoryClass = get_auth_handler_from_name(selected_auth_handler_class)

        # obtain configuration and instantiate AuthHandler
        selected_auth_handler_config = crud.get_auth_setting_by_name(
            name=selected_auth_handler_class
        )
        try:
            auth_handler = FactoryClass.get_auth_handler_from_config(
                selected_auth_handler_config["value"]
            )
        except Exception:
            import traceback

            traceback.print_exc()

            auth_handler = (
                auth_handlers.CoreOnlyAuthConfig.get_auth_handler_from_config({})
            )

        self.custom_auth_handler = auth_handler
        self.core_auth_handler = CoreAuthHandler()

    def send_ws_message(self, content: str, msg_type="notification"):
        log.error("No websocket connection open")
