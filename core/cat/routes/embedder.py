from typing import Dict
from fastapi import APIRouter, Body, Depends, Query

from cat.auth.connection import AdminConnectionAuth
from cat.auth.permissions import AdminAuthResource, AuthPermission
from cat.db.cruds import settings as crud_settings
from cat.exceptions import CustomValidationException
from cat.factory.base_factory import ReplacedNLPConfig
from cat.factory.embedder import EmbedderFactory
from cat.looking_glass.bill_the_lizard import BillTheLizard
from cat.routes.routes_utils import GetSettingsResponse, GetSettingResponse, UpsertSettingResponse

from cat.auth.connection import HTTPAuth, ContextualCats
from cat.auth.permissions import AuthPermission, AuthResource
from .memory.points import RecallResponseQuery


router = APIRouter()


# get configured Embedders and configuration schemas
@router.get("/settings", response_model=GetSettingsResponse)
async def get_embedders_settings(
    lizard: BillTheLizard = Depends(AdminConnectionAuth(AdminAuthResource.EMBEDDER, AuthPermission.LIST)),
) -> GetSettingsResponse:
    """Get the list of the Embedders"""

    factory = EmbedderFactory(lizard.plugin_manager)

    selected = crud_settings.get_setting_by_name(lizard.config_key, factory.setting_name)
    if selected is not None:
        selected = selected["value"]["name"]

    saved_settings = crud_settings.get_settings_by_category(lizard.config_key, factory.setting_factory_category)
    saved_settings = {s["name"]: s for s in saved_settings}

    settings = [GetSettingResponse(
        name=class_name,
        value=saved_settings[class_name]["value"] if class_name in saved_settings else {},
        scheme=scheme
    ) for class_name, scheme in factory.get_schemas().items()]

    return GetSettingsResponse(settings=settings, selected_configuration=selected)


@router.get("/settings/{embedder_name}", response_model=GetSettingResponse)
async def get_embedder_settings(
    embedder_name: str,
    lizard: BillTheLizard = Depends(AdminConnectionAuth(AdminAuthResource.EMBEDDER, AuthPermission.READ)),
) -> GetSettingResponse:
    """Get settings and scheme of the specified Embedder"""

    embedder_schemas = EmbedderFactory(lizard.plugin_manager).get_schemas()
    # check that embedder_name is a valid name
    allowed_configurations = list(embedder_schemas.keys())
    if embedder_name not in allowed_configurations:
        raise CustomValidationException(f"{embedder_name} not supported. Must be one of {allowed_configurations}")

    setting = crud_settings.get_setting_by_name(lizard.config_key, embedder_name)
    setting = {} if setting is None else setting["value"]

    scheme = embedder_schemas[embedder_name]

    return GetSettingResponse(name=embedder_name, value=setting, scheme=scheme)


@router.put("/settings/{embedder_name}", response_model=UpsertSettingResponse)
async def upsert_embedder_setting(
    embedder_name: str,
    payload: Dict = Body({"openai_api_key": "your-key-here"}),
    lizard: BillTheLizard = Depends(AdminConnectionAuth(AdminAuthResource.EMBEDDER, AuthPermission.EDIT)),
) -> ReplacedNLPConfig:
    """Upsert the Embedder setting"""

    embedder_schemas = EmbedderFactory(lizard.plugin_manager).get_schemas()
    # check that embedder_name is a valid name
    allowed_configurations = list(embedder_schemas.keys())
    if embedder_name not in allowed_configurations:
        raise CustomValidationException(f"{embedder_name} not supported. Must be one of {allowed_configurations}")

    return await lizard.replace_embedder(embedder_name, payload)

@router.get("/embedding", response_model=RecallResponseQuery)
async def get_embedding(
    text: str = Query(..., title="Text to embed"),
    ccats : ContextualCats = Depends(HTTPAuth(AdminAuthResource.EMBEDDER, AuthPermission.READ))
) -> RecallResponseQuery:
    """Get the embedding of the query"""
    ccat = ccats.cheshire_cat
    embedder = ccat.embedder
    response = RecallResponseQuery(
        text=text,
        vector=embedder.embed_query(text)
    )
    return response


