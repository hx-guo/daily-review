import pytest
from gdr.jsonutil import extract_json

def test_plain_json():
    assert extract_json('{"score": 80, "tags": ["GRB"]}') == {"score": 80, "tags": ["GRB"]}

def test_fenced_json():
    text = 'Here is the result:\n```json\n{"a": 1, "b": {"c": 2}}\n```\nDone.'
    assert extract_json(text) == {"a": 1, "b": {"c": 2}}

def test_prose_then_object():
    assert extract_json('分数如下 {"score": 55} 谢谢') == {"score": 55}

def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")
