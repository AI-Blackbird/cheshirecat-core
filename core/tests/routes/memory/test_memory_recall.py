from tests.utils import send_n_websocket_messages


# search on default startup memory
def test_memory_recall_default_success(client, cheshire_cat):
    params = {"text": "Red Queen"}
    response = client.get("/memory/recall/", params=params, headers={"agent_id": cheshire_cat.id})
    json = response.json()
    assert response.status_code == 200

    # query was received and embedded
    assert json["query"]["text"] == params["text"]
    assert isinstance(json["query"]["vector"], list)
    assert isinstance(json["query"]["vector"][0], float)

    # results are grouped by collection
    assert len(json["vectors"]["collections"]) == 3
    assert {"episodic", "declarative", "procedural"} == set(
        json["vectors"]["collections"].keys()
    )

    # initial collections contents
    for collection in json["vectors"]["collections"].keys():
        assert isinstance(json["vectors"]["collections"][collection], list)
        if collection == "procedural":
            assert len(json["vectors"]["collections"][collection]) > 0
        else:
            assert len(json["vectors"]["collections"][collection]) == 0


# search without query should throw error
def test_memory_recall_without_query_error(client, cheshire_cat):
    response = client.get("/memory/recall", headers={"agent_id": cheshire_cat.id})
    assert response.status_code == 400


# search with query
def test_memory_recall_success(client, cheshire_cat):
    # send a few messages via chat
    num_messages = 3
    send_n_websocket_messages(num_messages, client, agent_id=cheshire_cat.id)

    # recall
    params = {"text": "Red Queen"}
    response = client.get("/memory/recall/", params=params, headers={"agent_id": cheshire_cat.id})
    json = response.json()
    assert response.status_code == 200
    episodic_memories = json["vectors"]["collections"]["episodic"]
    assert len(episodic_memories) == num_messages  # all 3 retrieved


# search with query and k
def test_memory_recall_with_k_success(client, cheshire_cat):
    # send a few messages via chat
    num_messages = 6
    send_n_websocket_messages(num_messages, client, agent_id=cheshire_cat.id)

    # recall at max k memories
    max_k = 2
    params = {"k": max_k, "text": "Red Queen"}
    response = client.get("/memory/recall/", params=params, headers={"agent_id": cheshire_cat.id})
    json = response.json()
    assert response.status_code == 200
    episodic_memories = json["vectors"]["collections"]["episodic"]
    assert len(episodic_memories) == max_k  # only 2 of 6 memories recalled
