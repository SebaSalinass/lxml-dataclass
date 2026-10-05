from __future__ import annotations

from dataclasses import InitVar
from typing import ClassVar

import lxml.etree as ET
import pytest

from lxml_dataclass import Element, element_field


class Book(Element):
    __tag__ = "Book"
    title: str = element_field("Title")
    pages: int = element_field("Pages", default=50)


@pytest.mark.parametrize("tag", ["book", "Featured"])
def test_nested_model_and_tag_override(tag):
    class Author(Element):
        __tag__ = "Author"
        book: Book | None = element_field(tag, default=None)

    author = Author(Book("Example", 80))
    xml = author.to_string_element()
    assert author.to_lxml_element()[0].tag == ("Book" if tag == "book" else tag)
    assert Author.from_data(xml) == author
    assert Author.from_data(b"<Author/>").book is None


def test_nested_model_lists():
    class Author(Element):
        __tag__ = "Author"
        books: list[Book] = element_field("books", default_factory=list)

    author = Author([Book("A"), Book("B", 80)])
    assert [child.tag for child in author.to_lxml_element()] == ["Book", "Book"]
    assert Author.from_data(author.to_string_element()) == author


def test_nested_field_attributes():
    class Model(Element):
        __tag__ = "Model"
        book: Book = element_field("Featured", attrib={"role": "primary"})

    root = Model(Book("A")).to_lxml_element()
    assert root[0].tag == "Featured"
    assert root[0].get("role") == "primary"
    assert root[0][0].text == "A"


def test_recursive_forward_reference():
    class Node(Element):
        __tag__ = "Node"
        name: str
        child: Node | None = element_field("child", default=None)

    tree = Node("root", Node("leaf"))
    assert Node.from_data(tree.to_string_element()) == tree


class ForwardParent(Element):
    __tag__ = "ForwardParent"
    child: LaterChild = element_field("child")


class LaterChild(Element):
    __tag__ = "LaterChild"
    value: str


def test_module_forward_reference():
    parent = ForwardParent(LaterChild("x"))
    assert ForwardParent.from_data(parent.to_string_element()) == parent


def test_inheritance_order_and_subclass_override():
    class Base(Element):
        __tag__ = "Base"
        value: int = element_field("Old")

    class Child(Base):
        __tag__ = "Child"
        value: str = element_field("New")
        extra: str

    child = Child("x", "y")
    assert child.to_string_element() == b"<Child><New>x</New><extra>y</extra></Child>"
    assert Child.from_data(child.to_string_element()) == child
    assert Base(1).to_string_element() == b"<Base><Old>1</Old></Base>"


def test_multiple_inheritance_obeys_mro():
    class Left(Element):
        left: str
        shared: str = element_field("LeftShared")

    class Right(Element):
        right: str
        shared: str = element_field("RightShared")

    class Combined(Left, Right):
        __tag__ = "Combined"

    model = Combined(right="r", shared="s", left="l")
    assert (
        model.to_string_element()
        == b"<Combined><right>r</right><LeftShared>s</LeftShared><left>l</left></Combined>"
    )


def test_inherited_default_before_required_raises():
    class Base(Element):
        value: int = 1

    with pytest.raises(TypeError, match="non-default argument"):

        class Child(Base):
            required: str


def test_keyword_only_class_and_field_override():
    class Model(Element, kw_only=True):
        __tag__ = "Model"
        positional: str = element_field("Positional", kw_only=False)
        value: int
        extra: str = element_field("Extra", default="x")

    assert Model("p", value=2).value == 2
    with pytest.raises(TypeError):
        Model("p", 2)
    assert (
        Model.from_data(
            b"<Model><Positional>p</Positional><value>2</value></Model>"
        ).extra
        == "x"
    )


def test_keyword_only_mixin_default_before_required_field():
    class Mixin(Element):
        id: int = element_field("Id", default=1, kw_only=True)

    class Model(Mixin):
        __tag__ = "Model"
        name: str

    assert Model("x").id == 1
    assert Model("x", id=2).id == 2


def test_classvar_is_not_an_instance_or_xml_field():
    class Model(Element):
        __tag__: ClassVar[str] = "Model"
        constant: ClassVar[int] = 7
        value: str

    instance = Model("x")
    assert instance.constant == 7
    assert "constant" not in vars(instance)
    assert instance.to_string_element() == b"<Model><value>x</value></Model>"
    assert Model.from_data(instance.to_string_element()) == instance


def test_initvar_and_post_init():
    class Model(Element):
        __tag__ = "Model"
        value: int
        multiplier: InitVar[int] = 2

        def __post_init__(self, multiplier):
            self.value *= multiplier

    instance = Model(3, 4)
    assert instance.value == 12
    assert "multiplier" not in vars(instance)
    assert instance.to_string_element() == b"<Model><value>12</value></Model>"
    assert Model.from_data(b"<Model><value>3</value></Model>").value == 6


def test_factory_instances_are_independent():
    class Model(Element):
        values: list[int] = element_field("Value", default_factory=list)

    first, second = Model(), Model()
    first.values.append(1)
    assert second.values == []


def test_validators_run_on_init_assignment_and_parsing():
    def positive(field, value):
        if value < 0:
            raise ValueError(f"{field.name} must be positive")

    class Model(Element):
        __tag__ = "Model"
        value: int = element_field("Value", validators=[positive])

    with pytest.raises(ValueError, match="value must be positive"):
        Model(-1)
    instance = Model(1)
    with pytest.raises(ValueError):
        instance.value = -1
    assert instance.value == 1
    with pytest.raises(ValueError):
        Model.from_data(b"<Model><Value>-1</Value></Model>")


def test_validators_remain_after_ignored_field_parsing():
    def positive(field, value):
        if value < 0:
            raise ValueError("negative")

    class Model(Element):
        __tag__ = "Model"
        __ignored_fields__: ClassVar[list[str]] = ["value"]
        value: int = element_field("Value", default=1, validators=[positive])

    model = Model.from_data(b"<Model/>")
    with pytest.raises(ValueError):
        model.value = -1


def test_equality_compare_false_and_unrelated_types():
    class Model(Element):
        value: int
        ignored: str = element_field("Ignored", compare=False)

    assert Model(1, "a") == Model(1, "b")
    assert Model(1, "a") != Model(2, "a")
    assert Model(1, "a") != object()
    with pytest.raises(TypeError):
        hash(Model(1, "a"))


def test_custom_methods_are_preserved():
    class Model(Element):
        __tag__ = "Model"
        value: int

        def __init__(self, value):
            self.value = value + 1

        def __eq__(self, other):
            return isinstance(other, Model)

    assert Model(1).value == 2
    assert Model(1) == Model(99)


@pytest.mark.parametrize(
    "kwargs, exception, message",
    [
        ({"default": 1, "default_factory": list}, ValueError, "both default"),
        ({"default_factory": 3}, TypeError, "default_factory must be callable"),
        ({"coerce": 3}, TypeError, "coerce must be callable"),
    ],
)
def test_invalid_field_arguments(kwargs, exception, message):
    with pytest.raises(exception, match=message):
        element_field("Value", **kwargs)


def test_mutable_default_rejected():
    with pytest.raises(ValueError, match="mutable default"):

        class Model(Element):
            values: list[int] = []  # noqa: RUF012


def test_field_without_annotation_rejected():
    with pytest.raises(TypeError, match="no type annotation"):

        class Model(Element):
            value = element_field("Value")


def test_classvar_factory_and_kw_only_rejected():
    with pytest.raises(TypeError, match="default factory"):

        class Model(Element):
            value: ClassVar[int] = element_field("Value", default_factory=int)

    with pytest.raises(TypeError, match="specifies kw_only"):

        class Model(Element):
            value: ClassVar[int] = element_field("Value", kw_only=True)


def test_self_named_field_constructor():
    class Model(Element):
        __tag__ = "Model"
        self: str

    assert Model("x").to_string_element() == b"<Model><self>x</self></Model>"


def test_explicit_hash_is_preserved():
    class Model(Element):
        value: int

        def __hash__(self):
            return hash(self.value)

    assert hash(Model(1)) == hash(1)


def test_custom_init_allows_default_before_required():
    class Model(Element):
        first: int = 1
        second: str

        def __init__(self, second):
            self.first = 1
            self.second = second

    assert Model("x").second == "x"


def test_reannotated_inherited_default_is_preserved():
    class Base(Element):
        value: int = element_field("Original", default=1)

    class Child(Base):
        __tag__ = "Child"
        value: int

    assert Child().value == 1
    assert Child().to_string_element() == b"<Child><value>1</value></Child>"
    assert Base.__element_fields__["value"].tag == "Original"


def test_deferred_annotations_without_future_import():
    import sys
    import types

    module = types.ModuleType("_lxml_dataclass_annotation_test")
    sys.modules[module.__name__] = module
    try:
        # Isolated compilation exercises Python 3.14's deferred annotations.
        source = """from lxml_dataclass import Element, element_field
class Parent(Element):
    __tag__ = 'Parent'
    child: 'Child' = element_field('child')
class Child(Element):
    __tag__ = 'Child'
    value: str
"""
        exec(  # noqa: S102
            compile(source, "<annotation-test>", "exec", dont_inherit=True),
            vars(module),
        )
        instance = module.Parent(module.Child("x"))
        assert module.Parent.from_data(instance.to_string_element()) == instance
    finally:
        sys.modules.pop(module.__name__, None)


def test_nested_custom_serialization_method_is_preserved():

    class Child(Element):
        __tag__ = "Child"

        def to_lxml_element(self):
            root = ET.Element("Child")
            root.set("custom", "yes")
            return root

    class Parent(Element):
        __tag__ = "Parent"
        child: Child = element_field("child")

    assert Parent(Child()).to_lxml_element()[0].get("custom") == "yes"


def test_python314_forward_reference_without_quotes():
    import sys
    import types

    if sys.version_info < (3, 14):
        pytest.skip("Unquoted deferred forward references require Python 3.14")
    module = types.ModuleType("_lxml_dataclass_deferred_test")
    sys.modules[module.__name__] = module
    try:
        source = """from lxml_dataclass import Element, element_field
class Parent(Element):
    __tag__ = 'Parent'
    child: Child = element_field('child')
class Child(Element):
    __tag__ = 'Child'
    value: str
"""
        exec(  # noqa: S102
            compile(source, "<deferred-test>", "exec", dont_inherit=True), vars(module)
        )
        instance = module.Parent(module.Child("x"))
        assert module.Parent.from_data(instance.to_string_element()) == instance
    finally:
        sys.modules.pop(module.__name__, None)


def test_nested_custom_parsing_method_is_preserved():
    class Child(Element):
        __tag__ = "Child"
        value: str

        @classmethod
        def from_lxml_element(cls, element, prefix=""):
            return cls(element.get("value"))

    class Parent(Element):
        __tag__ = "Parent"
        child: Child = element_field("child")

    parsed = Parent.from_data(b'<Parent><Child value="custom"/></Parent>')
    assert parsed.child.value == "custom"
