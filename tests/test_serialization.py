from datetime import UTC, datetime
from typing import ClassVar

import lxml.etree as ET
import pytest

from lxml_dataclass import Element, LxmlElement, element_field


@pytest.mark.parametrize(
    "value, text", [(0, "0"), (False, "False"), (True, "True"), ("x", "x")]
)
def test_false_values_are_preserved(value, text):
    class Model(Element):
        __tag__ = "Model"
        value: object = element_field("Value", coerce=str)

    assert Model(value).to_lxml_element().find("Value").text == text


@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.parametrize("display_empty", [False, True])
def test_empty_scalars(value, display_empty):
    class Model(Element):
        __tag__ = "Model"
        value: str | None = element_field("Value", display_empty=display_empty)

    root = Model(value).to_lxml_element()
    assert len(root) == int(display_empty)
    if display_empty:
        assert root[0].text in (None, "")


@pytest.mark.parametrize("value", [None, [], ()])
def test_empty_collections_do_not_crash(value):
    class Model(Element):
        __tag__ = "Model"
        values: list[int] | None = element_field("Value", display_empty=True)

    assert Model(value).to_string_element() == b"<Model/>"


def test_scalar_format_and_escaping():
    class Model(Element):
        __tag__ = "Model"
        price: float = element_field("Price", format_spec=".2f")
        created: datetime = element_field("Created", format_spec="%Y-%m-%d")
        name: str = element_field("Name")

    root = Model(1.234, datetime(2026, 1, 2, tzinfo=UTC), "<a & b>").to_lxml_element()
    assert root[0].text == "1.23"
    assert root[1].text == "2026-01-02"
    xml = ET.tostring(root)
    assert b"&lt;a &amp; b&gt;" in xml
    assert ET.fromstring(xml)[2].text == "<a & b>"


def test_string_encoding_and_xml_options():
    class Model(Element):
        __tag__ = "Model"
        name: str

    model = Model("José")
    assert isinstance(model.to_lxml_element(), LxmlElement)
    assert (
        model.to_string_element(encoding="unicode")
        == "<Model><name>José</name></Model>"
    )
    assert model.to_string_element(encoding="utf-8", xml_declaration=True).startswith(
        b"<?xml"
    )


def test_missing_tag():
    class Model(Element):
        value: str

    with pytest.raises(AttributeError, match="__tag__"):
        Model("x").to_lxml_element()
    with pytest.raises(AttributeError, match="__tag__"):
        Model.from_data(b"<Model/>")


def test_root_and_field_attributes():
    class Model(Element):
        __tag__ = "Model"
        __attrib__: ClassVar[dict] = {"id": "1"}
        value: str = element_field("Value", attrib={"unit": "m"})

    model = Model("2")
    root = model.to_lxml_element()
    assert dict(root.attrib) == {"id": "1"}
    assert dict(root[0].attrib) == {"unit": "m"}
    model.__attrib__ = {"id": "2"}
    assert model.to_lxml_element().get("id") == "2"


def test_explicit_iterable_setting_is_respected():
    class Model(Element):
        __tag__ = "Model"
        values: object = element_field("Value", is_iterable=True, coerce=int)

    model = Model([1, 2])
    assert (
        model.to_string_element() == b"<Model><Value>1</Value><Value>2</Value></Model>"
    )
    assert Model.from_data(model.to_string_element()).values == [1, 2]

    class Scalar(Element):
        __tag__ = "Scalar"
        values: list[int] = element_field("Value", is_iterable=False, coerce=str)

    assert len(Scalar([1, 2]).to_lxml_element()) == 1
