import pytest

# test endpoints with different user permissions
# NOTE: we are using here the secure_client:
# - CCAT_API_KEY, CCAT_API_KEY_WS and CCAT_JWT_SECRET are active
# - we will auth with JWT

@pytest.mark.parametrize("endpoint", [
    {
        "method": "GET",
        "path": "/users",
        "payload": None
    },
    {
        "method": "GET",
        "path": "/users/ID_PLACEHOLDER",
        "payload": None
    },
    {
        "method": "POST",
        "path": "/users",
        "payload": {"username": "Alice", "password": "12345"}
    },
    {
        "method": "PUT",
        "path": "/users/ID_PLACEHOLDER",
        "payload": {"username": "Alice2"}
    },
    {
        "method": "DELETE",
        "path": "/users/ID_PLACEHOLDER",
        "payload": None
    }
])


def test_users_permissions(secure_client, cheshire_cat, endpoint):
    agent_id = cheshire_cat.id
    credentials = {"username": "user", "password": "user"}

    # create new user that will be edited by calling the endpoints
    # we create it using directly CCAT_API_KEY
    response = secure_client.post(
        "/users",
        json={
            "username": "Caterpillar",
            "password": "U R U"
        },
        headers={
            "Authorization": f"Bearer meow_http",
            "user_id": "admin",
            "agent_id": agent_id
        }
    )
    assert response.status_code == 200
    target_user_id = response.json()["id"]

    # tests for `admin` and `user` using the endpoints

    # no JWT, no pass
    res = secure_client.request(
        endpoint["method"],
        endpoint["path"].replace("ID_PLACEHOLDER", target_user_id),
        json=endpoint["payload"],
        headers={"agent_id": cheshire_cat.id}
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "Invalid Credentials"
    
    # obtain JWT
    res = secure_client.post("/auth/token", json=credentials, headers={"agent_id": cheshire_cat.id})
    assert res.status_code == 200
    jwt = res.json()["access_token"]

    # now using JWT
    res = secure_client.request(
        endpoint["method"],
        endpoint["path"].replace("ID_PLACEHOLDER", target_user_id),
        json=endpoint["payload"],
        headers={"Authorization": f"Bearer {jwt}", "agent_id": cheshire_cat.id} # using credentials
    )
    # `admin` can now use endpoints, `user` cannot
    if credentials["username"] == "admin":
        assert res.status_code == 200
    else:
        assert res.status_code == 403
