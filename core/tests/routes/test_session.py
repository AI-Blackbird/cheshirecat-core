from cat.convo.messages import Role
from cat.db import models
from cat.looking_glass.stray_cat import StrayCat

from tests.utils import send_websocket_message, api_key, agent_id


def test_session_creation_from_websocket(secure_client, cheshire_cat):
    user_id = models.generate_uuid()

    # send websocket message
    mex = {"text": "Where do I go?"}
    res = send_websocket_message(mex, secure_client, user_id=user_id)

    # check response
    assert "You did not configure" in res["content"]

    # verify session
    strays_user_ids = [s.user.id for s in cheshire_cat.strays]
    assert user_id in strays_user_ids
    stray_cat = cheshire_cat.get_stray(user_id)
    assert isinstance(stray_cat, StrayCat)
    assert stray_cat.user.id == user_id
    convo = stray_cat.working_memory.history
    assert len(convo) == 2
    assert convo[0].who == Role.HUMAN
    assert convo[0].message == mex["text"]


def test_session_creation_from_http(secure_client, cheshire_cat):
    user_id = models.generate_uuid()

    content_type = "text/plain"
    file_name = "sample.txt"
    file_path = f"tests/mocks/{file_name}"
    with open(file_path, "rb") as f:
        files = {"file": (file_name, f, content_type)}

        # sending file from Alice
        response = secure_client.post(
            "/rabbithole/",
            files=files,
            headers={"user_id": user_id, "access_token": api_key, "agent_id": agent_id},
        )

    # check response
    assert response.status_code == 200

    # verify session
    strays_user_ids = [s.user.id for s in cheshire_cat.strays]
    assert user_id in strays_user_ids
    stray_cat = cheshire_cat.get_stray(user_id)
    assert isinstance(stray_cat, StrayCat)
    assert stray_cat.user.id == user_id
    convo = stray_cat.working_memory.history
    assert len(convo) == 0  # no ws message sent from Alice


# TODO: how do we test that:
# - session is coherent between ws and http calls
# - streaming happens
# - hooks receive the correct session

# REFACTOR TODO: we still do not delete sessions
