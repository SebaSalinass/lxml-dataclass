from typing import ClassVar

import pytest

from lxml_dataclass import Element, element_field


@pytest.mark.parametrize(
    "tag, nsmap",
    [
        ("Model", {None: "urn:example"}),
        ("{urn:example}Model", {"ex": "urn:example"}),
        ("ex:Model", {"ex": "urn:example"}),
    ],
)
def test_namespace_round_trip(tag, nsmap):
    class Model(Element):
        __tag__ = tag
        __nsmap__ = nsmap
        value: str = element_field("{urn:example}Value")

    model = Model("x")
    assert model.to_lxml_element().tag == "{urn:example}Model"
    assert Model.from_data(model.to_string_element()) == model


def test_default_namespace_applies_to_implicit_children():
    class Model(Element):
        __tag__ = "Model"
        __nsmap__: ClassVar[dict] = {None: "urn:example"}
        value: int

    model = Model(1)
    root = model.to_lxml_element()
    assert root[0].tag == "{urn:example}value"
    assert (
        Model.from_lxml_element(root)
        == Model.from_data(model.to_string_element())
        == model
    )


def test_field_default_namespace_round_trip():
    class Model(Element):
        __tag__ = "Model"
        value: str = element_field("Value", nsmap={None: "urn:field"})

    model = Model("x")
    assert model.to_lxml_element()[0].tag == "{urn:field}Value"
    assert Model.from_data(model.to_string_element()) == model


def test_field_prefixed_namespace():
    class Model(Element):
        __tag__ = "Model"
        value: str = element_field("f:Value", nsmap={"f": "urn:field"})

    model = Model("x")
    assert Model.from_data(model.to_string_element()) == model


@pytest.mark.parametrize("prefix", ["{urn:example}", "ex:", "ex"])
def test_parsing_with_namespace_prefix(prefix):
    class Model(Element):
        __tag__ = "Model"
        value: int = element_field("Value")

    parsed = Model.from_data(
        b'<ex:Model xmlns:ex="urn:example"><ex:Value>2</ex:Value></ex:Model>',
        prefix=prefix,
    )
    assert parsed.value == 2


def test_unknown_prefix_error():
    class Model(Element):
        __tag__ = "unknown:Model"

    with pytest.raises(ValueError, match="Unknown XML namespace prefix"):
        Model().to_lxml_element()


def test_nested_default_namespace_round_trip():
    class Child(Element):
        __tag__ = "Child"
        value: int

    class Parent(Element):
        __tag__ = "Parent"
        __nsmap__: ClassVar[dict] = {None: "urn:example"}
        child: Child = element_field("child")

    model = Parent(Child(2))
    assert Parent.from_data(model.to_string_element()) == model
    assert Parent.from_lxml_element(model.to_lxml_element()) == model
    assert model.to_lxml_element()[0][0].tag == "{urn:example}value"


def test_nested_field_namespace_and_attributes_round_trip():
    class Child(Element):
        __tag__ = "Child"
        value: int

    class Parent(Element):
        __tag__ = "Parent"
        child: Child = element_field(
            "Featured", nsmap={None: "urn:child"}, attrib={"id": "1"}
        )

    model = Parent(Child(2))
    root = model.to_lxml_element()
    assert root[0].tag == "{urn:child}Featured"
    assert root[0][0].tag == "{urn:child}value"
    assert root[0].get("id") == "1"
    assert Parent.from_data(model.to_string_element()) == model
    assert Parent.from_lxml_element(root) == model


def test_configured_namespace_rejects_wrong_root_namespace():
    class Model(Element):
        __tag__ = "Model"
        __nsmap__: ClassVar[dict] = {None: "urn:expected"}
        value: str

    with pytest.raises(TypeError, match="root tag"):
        Model.from_data(b'<Model xmlns="urn:wrong"><value>x</value></Model>')


def test_nested_model_own_namespace():
    class Child(Element):
        __tag__ = "Child"
        __nsmap__: ClassVar[dict] = {None: "urn:child"}
        value: int

    class Parent(Element):
        __tag__ = "Parent"
        child: Child = element_field("child")

    model = Parent(Child(2))
    root = model.to_lxml_element()
    assert root[0].tag == "{urn:child}Child"
    assert root[0][0].tag == "{urn:child}value"
    assert Parent.from_lxml_element(root) == model
    assert Parent.from_data(model.to_string_element()) == model
