import asyncio
import pytest
import os
import shutil
from typing import Any, Generator
import warnings
from pydantic import PydanticDeprecatedSince20
from qdrant_client import QdrantClient
from fastapi.testclient import TestClient

from cat.auth.permissions import AuthUserInfo
from cat.looking_glass.cheshire_cat_manager import CheshireCatManager
from cat.looking_glass.stray_cat import StrayCat
from cat.mad_hatter.plugin import Plugin
from cat.main import cheshire_cat_api
from cat.memory.vector_memory import VectorMemory
import cat.utils as utils
from tests.utils import create_mock_plugin_zip


# substitute classes' methods where necessary for testing purposes
def mock_classes(monkeypatch):
    # Use in memory vector db
    def mock_connect_to_vector_memory(self, *args, **kwargs):
        return QdrantClient(":memory:")

    monkeypatch.setattr(
        VectorMemory, "connect_to_vector_memory", mock_connect_to_vector_memory
    )

    # Use mock utils plugin folder
    def get_test_plugin_folder():
        return "tests/mocks/mock_plugin_folder/"

    utils.get_plugins_path = get_test_plugin_folder

    # do not check plugin dependencies at every restart
    def mock_install_requirements(self, *args, **kwargs):
        pass

    monkeypatch.setattr(Plugin, "_install_requirements", mock_install_requirements)


# get rid of tmp files and folders used for testing
def clean_up_mocks():
    # clean up service files and mocks
    to_be_removed = [
        "cat/metadata-test.json",  # legacy position, now moved into mocks folder
        "tests/mocks/metadata-test.json",
        "tests/mocks/mock_plugin.zip",
        "tests/mocks/mock_plugin/settings.json",
        "tests/mocks/mock_plugin_folder/mock_plugin",
        "tests/mocks/empty_folder",
    ]
    for tbr in to_be_removed:
        if os.path.exists(tbr):
            if os.path.isdir(tbr):
                shutil.rmtree(tbr)
            else:
                os.remove(tbr)


# Main fixture for the FastAPI app
@pytest.fixture(scope="function")
def client(monkeypatch) -> Generator[TestClient, Any, None]:
    """
    Create a new FastAPI TestClient.
    """

    # clean up tmp files and folders
    clean_up_mocks()
    # monkeypatch classes
    mock_classes(monkeypatch)
    # delete all singletons!!!
    utils.singleton.instances = {}

    os.environ["CCAT_QDRANT_HOST"] = ""
    with TestClient(cheshire_cat_api) as client:
        yield client

    del os.environ["CCAT_QDRANT_HOST"]


@pytest.fixture(scope="function")
def cheshire_cat_manager():
    return CheshireCatManager()


# This fixture sets the CCAT_API_KEY and CCAT_API_KEY_WS environment variables,
# making mandatory for clients to possess api keys or JWT
@pytest.fixture(scope="function")
def secure_client(client):
    # set ENV variables
    os.environ["CCAT_API_KEY"] = "meow_http"
    os.environ["CCAT_API_KEY_WS"] = "meow_ws"
    yield client
    del os.environ["CCAT_API_KEY"]
    del os.environ["CCAT_API_KEY_WS"]


# This fixture is useful to write tests in which
#   a plugin was just uploaded via http.
#   It wraps any test function having `just_installed_plugin` as an argument
@pytest.fixture(scope="function")
def just_installed_plugin(client):
    ### executed before each test function

    # create zip file with a plugin
    zip_path = create_mock_plugin_zip(flat=True)
    zip_file_name = zip_path.split("/")[-1]  # mock_plugin.zip in tests/mocks folder

    # upload plugin via endpoint
    with open(zip_path, "rb") as f:
        response = client.post(
            "/plugins/upload/", files={"file": (zip_file_name, f, "application/zip")}
        )

    # request was processed
    assert response.status_code == 200
    assert response.json()["filename"] == zip_file_name

    ### each test function having `just_installed_plugin` as argument, is run here
    yield
    ###

    # clean up of zip file and mock_plugin_folder is done for every test automatically (see client fixture)

# fixtures to test the main agent
@pytest.fixture
def main_agent(client, cheshire_cat_manager):
    cheshire_cat = cheshire_cat_manager.get_or_create_cheshire_cat("test")

    yield cheshire_cat.main_agent  # each test receives as argument the main agent instance

# fixture to have available an instance of StrayCat
@pytest.fixture
def stray(client, cheshire_cat_manager):
    cheshire_cat = cheshire_cat_manager.get_or_create_cheshire_cat("test")

    user = AuthUserInfo(id="user_alice", name="Alice")
    stray_cat = StrayCat(user_data=user, main_loop=asyncio.new_event_loop(), chatbot_id=cheshire_cat.id)
    stray_cat.working_memory.user_message_json = {"user_id": user.id, "text": "meow"}

    cheshire_cat.add_stray(stray_cat)

    yield stray_cat

# autouse fixture will be applied to *all* the tests
@pytest.fixture(autouse=True)
def apply_warning_filters():
    # ignore deprecation warnings due to langchain not updating to pydantic v2
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)