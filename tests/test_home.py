def test_home_page_returns_expected_content(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert response.content == b"<html><body><h1>SkillSwap</h1></body></html>"
