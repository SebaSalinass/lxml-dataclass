from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, ClassVar, Optional

import lxml.etree as ET
import pytest

from lxml_dataclass import Element, element_field


class Scalars(Element):
    __tag__ = "Scalars"
    name: str
    number: int
    enabled: bool
    amount: Decimal


def test_implicit_fields_and_future_annotations_round_trip():
    model = Scalars("name", 0, False, Decimal("1.25"))
    assert Scalars.from_data(model.to_string_element()) == model


@pytest.mark.parametrize(
    "text, expected",
    [("True", True), ("false", False), ("1", True), ("0", False), (" FALSE ", False)],
)
def test_boolean_conversion(text, expected):
    xml = f"<Scalars><name>x</name><number>1</number><enabled>{text}</enabled><amount>2</amount></Scalars>"
    assert Scalars.from_data(xml).enabled is expected


def test_invalid_boolean_and_numeric_conversion():
    with pytest.raises(ValueError, match="Invalid boolean"):
        Scalars.from_data(
            "<Scalars><name>x</name><number>1</number><enabled>no</enabled><amount>2</amount></Scalars>"
        )
    with pytest.raises(ValueError):
        Scalars.from_data(
            "<Scalars><name>x</name><number>bad</number><enabled>True</enabled><amount>2</amount></Scalars>"
        )


def test_missing_fields_preserve_defaults_and_factories():
    class Model(Element):
        __tag__ = "Model"
        name: str = element_field("Name", default="default")
        values: list[int] = element_field("Value", default_factory=lambda: [7])

    first = Model.from_data(b"<Model/>")
    second = Model.from_data(b"<Model/>")
    assert first.name == "default"
    assert first.values == [7]
    first.values.append(8)
    assert second.values == [7]


def test_missing_required_scalar_has_clear_error():
    with pytest.raises(ValueError, match="Missing required XML field 'name'"):
        Scalars.from_data(b"<Scalars/>")


def test_absent_required_collection():
    class Model(Element):
        __tag__ = "Model"
        values: tuple[int, ...]

    assert Model.from_data(b"<Model/>").values == ()


@pytest.mark.parametrize(
    "annotation, expected",
    [(list[int], [1, 2]), (tuple[int, ...], (1, 2)), (Optional[list[int]], [1, 2])],  # noqa: UP045
)
def test_collection_types(annotation, expected):
    class Model(Element):
        __tag__ = "Model"
        values: annotation = element_field("Value")

    result = Model.from_data(b"<Model><Value>1</Value><Value>2</Value></Model>")
    assert result.values == expected
    assert Model.from_data(result.to_string_element()) == result


def test_optional_and_annotated_scalars():
    class Model(Element):
        __tag__ = "Model"
        value: Annotated[Optional[int], "quantity"] = element_field(  # noqa: UP045
            "Value", default=None
        )

    assert Model.from_data(b"<Model/>").value is None
    assert Model.from_data(b"<Model><Value>2</Value></Model>").value == 2
    assert Model.from_data(b"<Model><Value/></Model>").value is None


def test_present_empty_string_does_not_use_default():
    class Model(Element):
        __tag__ = "Model"
        value: str = element_field("Value", default="fallback", display_empty=True)

    assert Model.from_data(b"<Model><Value/></Model>").value == ""


def test_custom_coerce_and_any():
    class Model(Element):
        __tag__ = "Model"
        date: Any = element_field("Date", coerce=lambda text: tuple(text.split("-")))
        raw: Any = element_field("Raw")

    result = Model.from_data(b"<Model><Date>2026-01-02</Date><Raw>abc</Raw></Model>")
    assert result.date == ("2026", "01", "02")
    assert result.raw == "abc"


def test_unsupported_union_requires_explicit_converter():
    class Model(Element):
        __tag__ = "Model"
        value: int | str = element_field("Value")

    with pytest.raises(TypeError, match="provide coerce explicitly"):
        Model.from_data(b"<Model><Value>2</Value></Model>")

    class Converted(Element):
        __tag__ = "Converted"
        value: int | str = element_field("Value", coerce=str)

    assert Converted.from_data(b"<Converted><Value>2</Value></Converted>").value == "2"


def test_heterogeneous_tuple_requires_converter():
    class Model(Element):
        __tag__ = "Model"
        values: tuple[int, str] = element_field("Value")

    with pytest.raises(TypeError, match="homogeneous tuple"):
        Model.from_data(b"<Model><Value>2</Value></Model>")


def test_ignored_fields_do_not_mutate_class_metadata():
    class Model(Element):
        __tag__ = "Model"
        __ignored_fields__: ClassVar[list[str]] = ["secret"]
        secret: str = element_field("Secret", default="private")
        value: int = element_field("Value", default=1)

    before = dict(Model.__element_fields__)
    for _ in range(2):
        model = Model.from_data(
            b"<Model><Secret>external</Secret><Value>2</Value></Model>"
        )
        assert model.secret == "private"
        assert model.to_string_element() == b"<Model><Value>2</Value></Model>"
        assert Model.__element_fields__ == before
    Model.__ignored_fields__ = []
    assert b"<Secret>private</Secret>" in model.to_string_element()


def test_init_false_fields_parse_without_constructor_keyword():
    class Model(Element):
        __tag__ = "Model"
        value: int = element_field("Value", init=False, default=3)
        values: list[int] = element_field("Item", init=False, default_factory=list)

    assert Model().value == 3
    parsed = Model.from_data(b"<Model><Value>4</Value><Item>5</Item></Model>")
    assert parsed.value == 4
    assert parsed.values == [5]
    assert Model.from_data(b"<Model/>").value == 3


def test_parsed_attributes_are_detached_from_input():
    class Model(Element):
        __tag__ = "Model"

    root = ET.fromstring(b'<Model id="1"/>')
    parsed = Model.from_lxml_element(root)
    root.set("id", "2")
    assert parsed.__attrib__ == {"id": "1"}
    parsed.__attrib__["id"] = "3"
    assert root.get("id") == "2"


@pytest.mark.parametrize("method", ["from_data", "from_lxml_element"])
def test_wrong_root_tag(method):
    data = b"<Wrong/>" if method == "from_data" else ET.Element("Wrong")
    with pytest.raises(TypeError, match="root tag"):
        getattr(Scalars, method)(data)


def test_malformed_xml_and_parser_options():
    with pytest.raises(ET.XMLSyntaxError):
        Scalars.from_data(b"<Scalars>")
    xml = b"<Scalars><!-- comment --><name>x</name><number>1</number><enabled>True</enabled><amount>2</amount></Scalars>"
    parsed = Scalars.from_data(xml, parser=ET.XMLParser(remove_comments=True))
    assert parsed.name == "x"


def test_unresolved_annotation_error_and_explicit_coerce():
    class Model(Element):
        __tag__ = "Model"
        value: UnknownType = element_field("Value")  # noqa: F821

    with pytest.raises(TypeError, match="Cannot resolve annotation"):
        Model.from_data(b"<Model><Value>x</Value></Model>")

    class Converted(Element):
        __tag__ = "Converted"
        value: UnknownType = element_field("Value", coerce=str)  # noqa: F821

    assert Converted.from_data(b"<Converted><Value>x</Value></Converted>").value == "x"
