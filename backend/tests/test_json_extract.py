"""Tolerant JSON extraction — the safety net that keeps a chatty/truncated LLM
response from silently collapsing a differential (or any AI feature) to empty."""
from lib import json_extract


def test_clean_object():
    obj = json_extract.extract_obj('{"differential":[{"diagnosis":"ACS","weight":0.6}]}')
    assert obj is not None
    assert obj["differential"][0]["diagnosis"] == "ACS"


def test_markdown_fenced():
    obj = json_extract.extract_obj('```json\n{"a":1,"b":[1,2]}\n```')
    assert obj == {"a": 1, "b": [1, 2]}


def test_surrounding_prose():
    obj = json_extract.extract_obj('Sure!\n{"a":1}\nHope that helps.')
    assert obj == {"a": 1}


def test_truncated_mid_string():
    # response cut off inside a value at the token ceiling
    obj = json_extract.extract_obj('{"differential":[{"diagnosis":"ACS","reasoning":"the patient ha')
    assert obj is not None
    assert obj["differential"][0]["diagnosis"] == "ACS"


def test_truncated_mid_array_keeps_complete_elements():
    raw = '{"differential":[{"diagnosis":"ACS","weight":0.5},{"diagnosis":"PE","weight":0.3},{"diagnosis":"Aort'
    obj = json_extract.extract_obj(raw)
    assert obj is not None
    names = [d["diagnosis"] for d in obj["differential"]]
    assert "ACS" in names and "PE" in names  # the two complete entries survive


def test_truncated_after_comma():
    raw = '{"a":[{"x":1}],"b":[{"y":2}],'
    obj = json_extract.extract_obj(raw)
    assert obj is not None
    assert obj["a"][0]["x"] == 1


def test_array_extraction():
    arr = json_extract.extract_array('[{"question":"Q1"},{"question":"Q2"}]')
    assert arr is not None and len(arr) == 2


def test_array_truncated():
    arr = json_extract.extract_array('[{"question":"Q1","type":"text"},{"question":"Q2","ty')
    assert arr is not None
    assert arr[0]["question"] == "Q1"


def test_no_json_returns_none():
    assert json_extract.extract_obj("there is no json here") is None
    assert json_extract.extract_array("nope") is None
    assert json_extract.extract_obj("") is None
