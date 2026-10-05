# lxml-dataclass

Define XML models with annotated Python classes. `Element` generates an initializer
and value-based equality, while `element_field()` configures XML child elements.

Requires Python 3.11+ and lxml 5.4+.

## Installation

```bash
pip install lxml-dataclass
```

## Basic usage

```python
from lxml_dataclass import Element, element_field


class Author(Element):
    __tag__ = "Author"

    name: str = element_field("Name")
    last: str = element_field("LastName", default="Doe")

    def fullname(self) -> str:
        return f"{self.name} {self.last}"


author = Author("John")
assert author.fullname() == "John Doe"
assert author.to_string_element() == (
    b"<Author><Name>John</Name><LastName>Doe</LastName></Author>"
)
assert Author.from_data(author.to_string_element()) == author
```

Annotations without `element_field()` use the Python attribute name as the XML tag:

```python
class Quantity(Element):
    __tag__ = "Quantity"
    count: int


assert Quantity(0).to_string_element() == b"<Quantity><count>0</count></Quantity>"
```

`__tag__` is required for XML conversion. Ordinary methods can be added to models.
Annotate class configuration with `typing.ClassVar` if you want type annotations
on attributes such as `__tag__` or `__nsmap__`.

## Serialization and parsing

| Method | Behavior |
| --- | --- |
| `model.to_lxml_element()` | Creates a new `lxml.etree._Element` tree. |
| `model.to_string_element(**kwargs)` | Forwards options to `lxml.etree.tostring`; returns bytes by default or a string with `encoding="unicode"`. |
| `Model.from_lxml_element(root, prefix="")` | Checks the root tag and reads child elements into a model. |
| `Model.from_data(data, prefix="", **kwargs)` | Parses bytes or text with `lxml.etree.fromstring`, then reads the model. Options such as `parser` are forwarded to lxml. |

```python
import lxml.etree as ET

root = ET.fromstring(b"<Author><Name>Jane</Name></Author>")
author = Author.from_lxml_element(root)
assert author.last == "Doe"
assert isinstance(author.to_string_element(encoding="unicode"), str)
```

Parsing converts text using the annotation or an explicit `coerce` callable.
Supported annotations include scalar constructors such as `str`, `int`, `float`,
`Decimal`, and `UUID`; nested `Element` models; `list[T]`; homogeneous
`tuple[T, ...]`; and optional forms such as `T | None` or `Optional[T]`.
`Annotated[T, ...]` uses `T`, and `Any` reads text as strings.
Boolean parsing accepts `true`, `false`, `1`, and `0`, ignoring case and surrounding
whitespace. Invalid boolean text raises `ValueError`.

Postponed annotations, self references, and module-level forward references are
supported. A reference must resolve when XML conversion occurs; unresolved local
references can use an explicit `coerce`. Ambiguous unions, heterogeneous tuples,
and other unsupported generic types require an explicit converter.

### Missing and empty values

- A missing XML child preserves its `default` or calls its `default_factory`.
- A missing required scalar raises `ValueError` naming the field. Optional
  annotations still need `default=None` if the child may be absent.
- A missing collection without a default becomes an empty list or tuple.
- A present empty element reads as `""` for `str` and as `None` for other scalar
  converters. A custom converter is called only when text is present.
- Serialization preserves `0` and `False`. `None` and empty strings are omitted
  unless `display_empty=True`; empty collections always emit no children.

Unknown XML children are ignored. Repeated scalar tags use the first matching
child. Models represent the configured children, rather than preserving arbitrary
XML, comments, mixed content, or unmodeled child attributes.

## Nested models and collections

```python
class Book(Element):
    __tag__ = "Book"

    title: str = element_field("Title")
    pages: int = element_field("Pages", default=50)


class Library(Element):
    __tag__ = "Library"

    books: list[Book] = element_field("books", default_factory=list)
    featured: Book | None = element_field("Featured", default=None)


library = Library([Book("First"), Book("Second", 80)], featured=Book("Special"))
root = library.to_lxml_element()
assert [child.tag for child in root] == ["Book", "Book", "Featured"]
assert Library.from_data(library.to_string_element()) == library
```

For a nested model, a field tag equal to its Python attribute name uses the nested
model's `__tag__`. A different tag explicitly overrides the nested root tag.
Field attributes are applied to the nested root. Lists and tuples produce repeated
siblings without a wrapper element; collection behavior is inferred automatically.
Use `default_factory=list` for independent empty lists on each instance.

## Inheritance and initialization

Base fields precede subclass fields, and subclass declarations override inherited
fields in place. Required positional fields cannot follow fields with defaults,
including inherited defaults. Use keyword-only fields for mixin defaults:

```python
from uuid import UUID, uuid4


class HasIDMixin(Element):
    id: UUID = element_field("Id", default_factory=uuid4, kw_only=True)


class IdentifiedAuthor(HasIDMixin):
    __tag__ = "Author"
    name: str = element_field("Name")


author = IdentifiedAuthor("John")
assert isinstance(author.id, UUID)
```

`class Model(Element, kw_only=True)` makes its new fields keyword-only; an individual
field can override this with `kw_only=False`. Inherited fields retain their settings.

`init=False` removes a field from the constructor. Its default or factory is
initialized normally, and parsed XML is assigned after construction. `ClassVar`
attributes are excluded from initialization, equality, and XML conversion.
`dataclasses.InitVar` parameters are passed to `__post_init__` and excluded from
XML; give them defaults if the generated constructor should work during parsing.

Models support generated `__init__`, `__eq__`, and `__post_init__`, but are not
standard dataclass instances: utilities such as `dataclasses.asdict()` and
`dataclasses.replace()` do not apply. Generated value equality makes models
unhashable unless an explicit `__hash__` is supplied. Custom initializers and equality
methods are preserved; a custom initializer must accept the fields supplied by parsing.

## Attributes and namespaces

`__attrib__` and `__nsmap__` configure the root; `attrib` and `nsmap` on
`element_field()` configure children. Assign a new instance dictionary when changing
root attributes, so a class dictionary is not shared accidentally:

```python
author = Author("John")
author.__attrib__ = {"id": "123"}
assert author.to_lxml_element().get("id") == "123"
```

Parsed root attributes and namespace dictionaries are copied from the input tree.

Use Clark notation (`{namespace-uri}local-name`) for explicit namespaced tags:

```python
class NamespacedAuthor(Element):
    __tag__ = "{urn:books}Author"
    __nsmap__ = {"books": "urn:books"}

    name: str = element_field("{urn:books}Name")


model = NamespacedAuthor("John")
assert NamespacedAuthor.from_data(model.to_string_element()) == model
```

Prefixed tags such as `books:Name` resolve through the namespace map. A default
namespace (`{None: "urn:books"}`) qualifies unqualified root and child tags,
including nested models. Field namespace maps extend or override inherited maps.
Declaring a named prefix alone does not qualify an unqualified tag.

For parsing existing XML with unqualified model definitions, `prefix="{urn:books}"`
or `prefix="books:"` selects namespaced tags. The named prefix must exist in the
input XML or field namespace map. For consistent namespaced output, define the
namespace in your model tags or use a default namespace.

## Field options

| Option | Purpose |
| --- | --- |
| `tag` | Required child tag; see nested model tag rules above. |
| `attrib`, `nsmap` | XML attributes and namespace declarations. |
| `default`, `default_factory` | A default value or zero-argument factory; mutually exclusive. Mutable defaults require a factory. |
| `display_empty=False` | Emit empty scalar elements for `None` or empty strings. |
| `format_spec=None` | Python format specification for serialization, such as `.2f` or `%Y-%m-%d` for a datetime. |
| `coerce=None` | Convert XML text during parsing; defaults to the annotation's constructor. |
| `is_iterable=None` | Infer repeated children from the annotation; `True` or `False` overrides inference. |
| `validators=None` | Callables receiving `(field, value)` during initialization and assignment; raise an exception to reject a value. |
| `compare=True` | Include the field in generated equality. |
| `init=True` | Include the field in the generated constructor. |
| `kw_only` | Override the class keyword-only setting for this field. |

Formatting and coercion are independent: a datetime formatting specification does
not provide a datetime parser. Supply a converter such as `datetime.fromisoformat`.
Validators check assignment, including parsed values, but do not intercept in-place
mutations such as `model.books.append(...)`. Type annotations configure conversion;
they do not enforce Python value types during assignment.

Set `__ignored_fields__ = ["field_name"]` to exclude fields from serialization and
parsing while retaining constructor behavior, validators, and comparison settings.
Ignored fields need defaults or a compatible custom initializer for parsing.

## Development

```bash
uv sync
uv run pytest
uv run mypy src/lxml_dataclass
```

Alternatively:

```bash
python -m pip install -e . pytest mypy lxml-stubs build
python -m pytest
python -m mypy src/lxml_dataclass
python -m build
```

The uv configuration builds lxml from source. If your machine lacks the required
compiler or libraries, use the pip alternative with a compatible lxml wheel.

CI builds the package and tests the installed wheel on Python 3.11–3.14, including
lxml 5.4.0 on Python 3.11. Releases run these checks before publishing.

## Compatibility notes

These fixes change some previous behaviors: false scalar values are preserved,
missing children retain defaults, subclass fields override base fields, and inherited
fields use dataclass ordering. Explicit nested tag overrides are now honored, and
both parsing entry points validate the root tag. Default namespaces now qualify
actual lxml tags as well as serialized XML.
