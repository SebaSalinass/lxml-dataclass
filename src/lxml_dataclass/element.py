import copy
import dataclasses
import inspect
import re
import sys
import types
import typing as t

import lxml.etree as ET  # type: ignore

__all__ = ("Element", "LxmlElement", "element_field")

LxmlElement: t.TypeAlias = ET._Element


class _FIELD_BASE:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class _MISSING_TYPE:
    pass


class _HAS_DEFAULT_FACTORY_CLASS:
    pass


_FIELD = _FIELD_BASE("_FIELD")
_FIELD_CLASSVAR = _FIELD_BASE("_FIELD_CLASSVAR")
_FIELD_INITVAR = _FIELD_BASE("_FIELD_INITVAR")
_FIELDS = "__element_fields__"
_IGNORED_FIELDS = "__ignored_fields__"
_MODULE_IDENTIFIER_RE = re.compile(r"^(?:\s*(\w+)\s*\.)?\s*(\w+)")
_HAS_DEFAULT_FACTORY = _HAS_DEFAULT_FACTORY_CLASS()
MISSING = _MISSING_TYPE()


InitVar = dataclasses.InitVar


# Field and Field Descriptors.
class ElementField:
    __slots__ = (
        "_field_type",
        "attrib",
        "coerce",
        "compare",
        "default",
        "default_factory",
        "display_empty",
        "format_spec",
        "init",
        "is_iterable",
        "kw_only",
        "localns",
        "name",
        "nsmap",
        "owner",
        "tag",
        "type",
        "validators",
    )

    def __init__(
        self,
        tag,
        attrib,
        nsmap,
        display_empty,
        validators,
        format_spec,
        is_iterable,
        compare,
        default,
        default_factory,
        coerce,
        init,
        kw_only,
    ):
        self.owner = None
        self.localns = {}
        self.name = None
        self.type = None
        self.tag = tag
        self.attrib = attrib
        self.nsmap = nsmap
        self.display_empty = display_empty
        self.validators = validators or []
        self.format_spec = format_spec
        self.is_iterable = is_iterable
        self.compare = compare
        self.default = default
        self.default_factory = default_factory
        self.coerce = coerce
        self.init = init
        self.kw_only = kw_only
        self._field_type = None

    def __str__(self):
        return f"<ElementField {self.name} -> {self.type}>"

    def validate_value(self, value):
        for validator in self.validators:
            validator(self, value)

    def _resolved_type(self):
        annotation = self.type
        if isinstance(annotation, (str, t.ForwardRef)) or t.get_args(annotation):
            holder = types.SimpleNamespace(__annotations__={"value": annotation})
            module = sys.modules.get(self.owner.__module__)
            globalns = vars(module) if module else {}
            localns = dict(self.localns)
            localns[self.owner.__name__] = self.owner
            try:
                annotation = t.get_type_hints(holder, globalns, localns)["value"]
            except (NameError, TypeError) as exc:
                if self.coerce is not None:
                    return t.Any
                raise TypeError(
                    f"Cannot resolve annotation for field {self.name!r}; "
                    "use a resolvable annotation or an explicit coerce callable"
                ) from exc
        return _unwrap_annotation(annotation)

    def _collection_type(self):
        return t.get_origin(self._resolved_type())

    def _is_iterable(self):
        if self.is_iterable is not None:
            return self.is_iterable
        return self._collection_type() in (list, tuple)

    def _converter(self):
        if self.coerce is not None:
            return self.coerce
        annotation = self._resolved_type()
        if self._is_iterable():
            args = t.get_args(annotation)
            if (
                t.get_origin(annotation) is tuple
                and args
                and (len(args) != 2 or args[1] is not Ellipsis)
            ):
                raise TypeError(
                    f"Field {self.name!r} requires a homogeneous tuple[T, ...]"
                )
            annotation = _unwrap_annotation(args[0]) if args else str
        if annotation in (t.Any, list, tuple):
            return str
        if t.get_origin(annotation) is not None or not callable(annotation):
            raise TypeError(
                f"Unsupported annotation for field {self.name!r}: {annotation!r}; "
                "provide coerce explicitly"
            )
        return annotation

    def _xml_tag(self):
        converter = self._converter()
        if self.tag == self.name and _is_element_class(converter):
            return _class_tag(converter)
        return self.tag

    def _namespace_map(self, nsmap):
        converter = self._converter()
        model_nsmap = (
            getattr(converter, "__nsmap__", None)
            if _is_element_class(converter)
            else None
        )
        return {**(nsmap or {}), **(model_nsmap or {}), **(self.nsmap or {})}

    def _element_from_value(self, value, nsmap):
        field_nsmap = self._namespace_map(nsmap)
        tag = _qualified_tag(self._xml_tag(), nsmap=field_nsmap)
        if isinstance(value, Element):
            if type(value).to_lxml_element is Element.to_lxml_element:
                element = value._to_lxml_element(field_nsmap)
            else:
                element = value.to_lxml_element()
            element.tag = tag
            if self.attrib:
                element.attrib.update(self.attrib)
            if field_nsmap:
                replacement = ET.Element(tag, dict(element.attrib), field_nsmap)
                replacement.text = element.text
                replacement.tail = element.tail
                replacement.extend(element)
                element = replacement
            return element

        element = ET.Element(tag, self.attrib, field_nsmap or None)
        if value is not MISSING and value is not None:
            element.text = (
                format(value, self.format_spec) if self.format_spec else str(value)
            )
        return element

    def process_value(self, value, nsmap=None):
        if self._is_iterable():
            if value is None or value is MISSING:
                return []
            return [self._element_from_value(item, nsmap) for item in value]
        return self._element_from_value(value, nsmap)

    def _value_from_element(self, element, prefix):
        converter = self._converter()
        if _is_element_class(converter):
            if (
                converter.from_lxml_element.__func__
                is not Element.from_lxml_element.__func__
            ):
                return converter.from_lxml_element(element, prefix)
            # The field already selected the child, including any tag override.
            return converter._from_lxml_element(element, prefix)
        if element.text is None:
            return "" if converter is str else None
        if converter is bool:
            value = element.text.strip().lower()
            if value in ("true", "1"):
                return True
            if value in ("false", "0"):
                return False
            raise ValueError(
                f"Invalid boolean for field {self.name!r}: {element.text!r}"
            )
        return converter(element.text)

    def process_element(self, element, prefix, nsmap=None):
        nsmap = self._namespace_map({**element.nsmap, **(nsmap or {})})
        find_tag = _qualified_tag(self._xml_tag(), prefix, nsmap)
        matches = [child for child in element if child.tag == find_tag]
        if not matches:
            return MISSING
        if self._is_iterable():
            values = [self._value_from_element(child, prefix) for child in matches]
            return tuple(values) if self._collection_type() is tuple else values
        return self._value_from_element(matches[0], prefix)


def element_field(
    tag: str,
    *,
    attrib=None,
    nsmap=None,
    display_empty=False,
    validators=None,
    format_spec=None,
    is_iterable=None,
    compare=True,
    default=MISSING,
    default_factory=MISSING,
    coerce=None,
    init=True,
    kw_only=MISSING,
) -> t.Any:
    """Configure an XML child field on an Element model.

    Collection behavior is inferred from list[T] and tuple[T, ...] unless
    is_iterable is supplied. coerce converts XML text during parsing only.
    Validators receive (field, value) on initialization and assignment.
    Missing XML preserves defaults; display_empty emits empty scalar elements.
    kw_only inherits the class setting unless explicitly supplied.
    """
    if default is not MISSING and default_factory is not MISSING:
        raise ValueError("cannot specify both default and default_factory")
    if default_factory is not MISSING and not callable(default_factory):
        raise TypeError("default_factory must be callable")
    if coerce is not None and not callable(coerce):
        raise TypeError("coerce must be callable")
    return ElementField(
        tag,
        attrib,
        nsmap,
        display_empty,
        validators,
        format_spec,
        is_iterable,
        compare,
        default,
        default_factory,
        coerce,
        init,
        kw_only,
    )


def _unwrap_annotation(annotation):
    if t.get_origin(annotation) is t.Annotated:
        return _unwrap_annotation(t.get_args(annotation)[0])
    if t.get_origin(annotation) in (t.Union, types.UnionType):
        args = [arg for arg in t.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return _unwrap_annotation(args[0])
    return annotation


def _is_element_class(value):
    return isinstance(value, type) and issubclass(value, Element)


def _class_tag(cls):
    tag = getattr(cls, "__tag__", None)
    if not tag:
        raise AttributeError("You must define __tag__ class attribute")
    return tag


def _qualified_tag(tag, prefix="", nsmap=None):
    """Resolve Clark notation, namespace prefixes, or a default namespace."""
    if tag.startswith("{"):
        return tag
    nsmap = nsmap or {}
    if ":" in tag:
        key, local = tag.split(":", 1)
        if key not in nsmap:
            raise ValueError(f"Unknown XML namespace prefix {key!r}")
        return f"{{{nsmap[key]}}}{local}"
    if prefix:
        if prefix.startswith("{") and prefix.endswith("}"):
            return f"{prefix}{tag}"
        key = prefix.removesuffix(":")
        if key not in nsmap:
            raise ValueError(f"Unknown XML namespace prefix {key!r}")
        return f"{{{nsmap[key]}}}{tag}"
    if nsmap.get(None):
        return f"{{{nsmap[None]}}}{tag}"
    return tag


# Type Checkers
def _is_classvar(a_type, typing):
    return a_type is typing.ClassVar or typing.get_origin(a_type) is typing.ClassVar


def _is_initvar(a_type, module):
    # The module we're checking against is the module we're
    # currently in (dataclasses.py).
    return a_type is module.InitVar or type(a_type) is module.InitVar


def _is_type(annotation, cls, a_module, a_type, is_type_predicate):
    match = _MODULE_IDENTIFIER_RE.match(annotation)
    if match:
        ns = None
        module_name = match.group(1)
        if not module_name:
            # No module name, assume the class's module did
            # "from dataclasses import InitVar".
            ns = sys.modules.get(cls.__module__).__dict__
        else:
            # Look up module_name in the class's module.
            module = sys.modules.get(cls.__module__)
            if module and module.__dict__.get(module_name) is a_module:
                ns = sys.modules.get(a_type.__module__).__dict__
        if ns and is_type_predicate(ns.get(match.group(2)), a_module):
            return True
    return False


# Field generation
def _get_field(cls, a_name, a_type, default_kw_only, localns, typing=None):
    default = getattr(cls, a_name, MISSING)

    if isinstance(default, ElementField):
        f = copy.copy(default)
    else:
        if isinstance(default, types.MemberDescriptorType):
            default = MISSING
        f = element_field(a_name, default=default)

    f.owner = cls
    f.localns = localns
    f.name = a_name
    f.type = a_type
    f._field_type = _FIELD

    if typing and (
        _is_classvar(a_type, typing)
        or (
            isinstance(f.type, str)
            and _is_type(f.type, cls, typing, typing.ClassVar, _is_classvar)
        )
    ):
        f._field_type = _FIELD_CLASSVAR

    if f._field_type is _FIELD:
        module = dataclasses
        if _is_initvar(a_type, module) or (
            isinstance(f.type, str)
            and _is_type(f.type, cls, module, module.InitVar, _is_initvar)
        ):
            f._field_type = _FIELD_INITVAR

    # Validations for individual fields.  This is delayed until now,
    # instead of in the Field() constructor, since only here do we
    # know the field name, which allows for better error reporting.

    if (
        f._field_type in (_FIELD_CLASSVAR, _FIELD_INITVAR)
        and f.default_factory is not MISSING
    ):
        raise TypeError(f"field {f.name} cannot have a default factory")

    # kw_only validation and assignment.
    if f._field_type in (_FIELD, _FIELD_INITVAR):
        # For real and InitVar fields, if kw_only wasn't specified use the
        # default value.
        if f.kw_only is MISSING:
            f.kw_only = default_kw_only
    else:
        # Make sure kw_only isn't set for ClassVars
        assert f._field_type is _FIELD_CLASSVAR
        if f.kw_only is not MISSING:
            raise TypeError(f"field {f.name} is a ClassVar but specifies kw_only")

    # For real fields, disallow mutable defaults.  Use unhashable as a proxy
    # indicator for mutability.  Read the __hash__ attribute from the class,
    # not the instance.
    if f._field_type is _FIELD and f.default.__class__.__hash__ is None:
        raise ValueError(
            f"mutable default {type(f.default)} for field "
            f"{f.name} is not allowed: use default_factory"
        )

    return f


def _fields_in_init_order(fields):
    return (
        tuple(f for f in fields if f.init and not f.kw_only),
        tuple(f for f in fields if f.init and f.kw_only),
    )


# Function generation
def _set_qualname(cls, value):
    # Ensure that the functions returned from _create_fn uses the proper
    # __qualname__ (the class they belong to).
    if isinstance(value, types.FunctionType):
        value.__qualname__ = f"{cls.__qualname__}.{value.__name__}"
    return value


def _set_new_attribute(cls, name, value):
    if name in cls.__dict__:
        return True
    _set_qualname(cls, value)
    setattr(cls, name, value)
    return False


def _init_param(f):
    # Return the __init__ parameter string for this field.  For
    # example, the equivalent of 'x:int=3' (except instead of 'int',
    # reference a variable set to int, and instead of '3', reference a
    # variable set to 3).
    if f.default is MISSING and f.default_factory is MISSING:
        # There's no default, and no default_factory, just output the
        # variable name and type.
        default = ""
    elif f.default is not MISSING:
        # There's a default, this will be the name that's used to look
        # it up.
        default = f"=_dflt_{f.name}"
    elif f.default_factory is not MISSING:
        # There's a factory function.  Set a marker.
        default = "=_HAS_DEFAULT_FACTORY"
    return f"{f.name}:_type_{f.name}{default}"


def _field_assign(name, value, self_name):
    return f"{self_name}.{name} = {value}"


def _field_init(f, globals, self_name):
    # Return the text of the line in the body of __init__ that will
    # initialize this field.
    if not f.name:
        raise AttributeError("Given ElementField name attribute is not set.")

    default_name = f"_dflt_{f.name}"
    if f.default_factory is not MISSING:
        globals[default_name] = f.default_factory
        if f.init:
            value = (
                f"{default_name}() if {f.name} is _HAS_DEFAULT_FACTORY else {f.name}"
            )
        else:
            value = f"{default_name}()"
    else:
        if f.init:
            if f.default is MISSING:
                value = f.name
            else:
                globals[default_name] = f.default
                value = f.name
        elif f.default is not MISSING:
            globals[default_name] = f.default
            value = default_name
        else:
            return None

    if f._field_type is _FIELD_INITVAR:
        return None

    # Now, actually generate the field assignment.
    return _field_assign(f.name, value, self_name)


def _create_fn(
    name,
    args,
    body,
    *,
    globals=None,
    locals=None,
    return_type=MISSING,
):
    # Note that we may mutate locals. Callers beware!
    # The only callers are internal to this module, so no
    # worries about external callers.
    if locals is None:
        locals = {}
    return_annotation = ""
    if return_type is not MISSING:
        locals["_return_type"] = return_type
        return_annotation = "->_return_type"
    _args = ",".join(args)
    _body = "\n".join(f"  {b}" for b in body)

    # Compute the text of the entire function.
    txt = f" def {name}({_args}){return_annotation}:\n{_body}"

    local_vars = ", ".join(locals.keys())
    txt = f"def __create_fn__({local_vars}):\n{txt}\n return {name}"
    ns = {}
    exec(txt, globals, ns)  # noqa: S102
    return ns["__create_fn__"](**locals)


def _tuple_str(obj_name, fields):
    # Return a string representing each field of obj_name as a tuple
    # member.  So, if fields is ['x', 'y'] and obj_name is "self",
    # return "(self.x,self.y)".

    # Special case for the 0-tuple.
    if not fields:
        return "()"
    # Note the trailing comma, needed if this turns out to be a 1-tuple.
    return f"({','.join([f'{obj_name}.{f.name}' for f in fields])},)"


def _init_fn(
    fields,
    std_fields,
    kw_only_fields,
    self_name,
    globals,
    has_post_init,
):
    seen_default = False

    for f in std_fields:
        if f.init:
            if not (f.default is MISSING and f.default_factory is MISSING):
                seen_default = True
            elif seen_default:
                raise TypeError(
                    f"non-default argument {f.name!r} follows default argument"
                )

    locals = {f"_type_{f.name}": f.type for f in fields}
    locals.update(
        {
            "MISSING": MISSING,
            "_HAS_DEFAULT_FACTORY": _HAS_DEFAULT_FACTORY,
            "__dataclass_builtins_object__": object,
        }
    )

    body_lines = []
    for f in fields:
        line = _field_init(f, locals, self_name)
        if line:
            body_lines.append(line)

    if has_post_init:
        args = ",".join(f.name for f in fields if f._field_type is _FIELD_INITVAR)
        body_lines.append(f"{self_name}.__post_init__({args})")

    # If no body lines, use 'pass'.
    if not body_lines:
        body_lines = ["pass"]

    _init_params = [_init_param(f) for f in std_fields]
    if kw_only_fields:
        # Add the keyword-only args.  Because the * can only be added if
        # there's at least one keyword-only arg, there needs to be a test here
        # (instead of just concatenting the lists together).
        _init_params += ["*"]
        _init_params += [_init_param(f) for f in kw_only_fields]
    return _create_fn(
        "__init__",
        [self_name] + _init_params,
        body_lines,
        locals=locals,
        globals=globals,
        return_type=None,
    )


def _cmp_fn(name, op, self_tuple, other_tuple, globals):
    # Create a comparison function.  If the fields in the object are
    # named 'x' and 'y', then self_tuple is the string
    # '(self.x,self.y)' and other_tuple is the string
    # '(other.x,other.y)'.

    return _create_fn(
        name,
        ("self", "other"),
        [
            "if other.__class__ is self.__class__:",
            f" return {self_tuple}{op}{other_tuple}",
            "return NotImplemented",
        ],
        globals=globals,
    )


# Complete class process
def _process_class(cls, kw_only: bool = False, localns=None):
    fields: dict[str, ElementField] = {}

    if cls.__module__ in sys.modules:
        globals = sys.modules[cls.__module__].__dict__
    else:
        globals = {}

    localns = {**(localns or {}), **vars(cls), cls.__name__: cls}
    if sys.version_info >= (3, 14):
        import annotationlib

        cls_annotations = inspect.get_annotations(
            cls, format=annotationlib.Format.FORWARDREF
        )
    else:
        cls_annotations = inspect.get_annotations(cls)
    # Resolve known annotations now; self and module forward references can
    # also be resolved by ElementField when XML is read or written.
    for name, annotation in cls_annotations.items():
        try:
            holder = types.SimpleNamespace(__annotations__={"value": annotation})
            cls_annotations[name] = t.get_type_hints(holder, globals, localns)["value"]
        except (NameError, TypeError):
            pass
    cls_fields = []

    for base in cls.__mro__[-1:0:-1]:
        fields.update(getattr(base, _FIELDS, {}))

    typing = sys.modules.get("typing")

    for f_name, f_type in cls_annotations.items():
        cls_fields.append(_get_field(cls, f_name, f_type, kw_only, localns, typing))

    for f in cls_fields:
        fields[f.name] = f
        if f.name and isinstance(getattr(cls, f.name, None), ElementField):
            if f.default is not MISSING:
                setattr(cls, f.name, f.default)
            else:
                delattr(cls, f.name)

    for name, value in cls.__dict__.items():
        if isinstance(value, ElementField) and name not in cls_annotations:
            raise TypeError(f"{name!r} is a field but has no type annotation")

    setattr(cls, _FIELDS, fields)

    all_init_fields = [
        f for f in fields.values() if f._field_type is not _FIELD_CLASSVAR
    ]

    (std_init_fields, kw_only_init_fields) = _fields_in_init_order(all_init_fields)

    if "__init__" not in cls.__dict__:
        _set_new_attribute(
            cls,
            "__init__",
            _init_fn(
                all_init_fields,
                std_init_fields,
                kw_only_init_fields,
                "__dataclass_self__" if "self" in fields else "self",
                globals,
                hasattr(cls, "__post_init__"),
            ),
        )

    # Create __eq__ method.  There's no need for a __ne__ method,
    # since python will call __eq__ and negate it.
    field_list = [f for f in fields.values() if f._field_type is _FIELD]
    flds = [f for f in field_list if f.compare]
    self_tuple = _tuple_str("self", flds)
    other_tuple = _tuple_str("other", flds)
    if (
        not _set_new_attribute(
            cls,
            "__eq__",
            _cmp_fn("__eq__", "==", self_tuple, other_tuple, globals=globals),
        )
        and "__hash__" not in cls.__dict__
    ):
        cls.__hash__ = None

    return cls


# Custom Metaclass
@t.dataclass_transform(field_specifiers=(element_field, ElementField))
class ElementMeta(type):
    def __new__(
        cls,
        name,
        bases,
        namespace,
        *,
        kw_only=False,
    ):
        class_ = super().__new__(cls, name, bases, namespace)
        frame = inspect.currentframe()
        try:
            localns = dict(frame.f_back.f_locals) if frame and frame.f_back else {}
        finally:
            del frame
        processed_class = _process_class(class_, kw_only, localns)

        return processed_class


# Usable Element Class
class Element(metaclass=ElementMeta):
    """Base for annotated XML models with generated initialization and equality."""

    def __setattr__(self, /, __name, __value):
        fields = getattr(self.__class__, _FIELDS, {})

        if field := fields.get(__name):
            field.validate_value(__value)
        object.__setattr__(self, __name, __value)

    def to_lxml_element(self) -> LxmlElement:
        """Build a new lxml tree from this model and its nested models."""
        return self._to_lxml_element()

    def _to_lxml_element(self, inherited_nsmap=None) -> LxmlElement:
        tag = _class_tag(self.__class__)

        attrib = getattr(self, "__attrib__", None)
        nsmap = {**(inherited_nsmap or {}), **(getattr(self, "__nsmap__", None) or {})}

        root = ET.Element(_qualified_tag(tag, nsmap=nsmap), attrib, nsmap or None)
        fields = getattr(self.__class__, _FIELDS, {})
        ignored_fields = getattr(self.__class__, _IGNORED_FIELDS, [])

        for field_name, element_field in fields.items():
            if field_name in ignored_fields or element_field._field_type is not _FIELD:
                continue

            value = getattr(self, field_name, None)
            if (
                value is None
                or value is MISSING
                or (isinstance(value, str) and value == "")
            ) and not element_field.display_empty:
                continue

            root_operation = (
                root.extend if element_field._is_iterable() else root.append
            )
            root_operation(element_field.process_value(value, nsmap))

        return root

    def to_string_element(self, **kwargs) -> bytes | str:
        """Serialize with lxml.etree.tostring options.

        Returns bytes by default, or str with encoding="unicode".
        """
        return ET.tostring(self.to_lxml_element(), **kwargs)

    @classmethod
    def from_lxml_element(cls, element: LxmlElement, prefix: str = "") -> t.Self:
        """Parse a matching XML root; preserve defaults for absent children."""
        nsmap = {**element.nsmap, **(getattr(cls, "__nsmap__", None) or {})}
        expected = _qualified_tag(_class_tag(cls), prefix, nsmap)
        if element.tag != expected:
            raise TypeError(
                f"The given data root tag is not equal to this class tag "
                f"data_tag={element.tag}, class_tag={expected}"
            )
        return cls._from_lxml_element(element, prefix)

    @classmethod
    def _from_lxml_element(cls, element: LxmlElement, prefix: str = "") -> t.Self:
        constructor_dict: dict[str, t.Any] = {}
        assignments: dict[str, t.Any] = {}
        ignored_fields = getattr(cls, _IGNORED_FIELDS, ())
        for field_name, field in getattr(cls, _FIELDS, {}).items():
            if field_name in ignored_fields or field._field_type is not _FIELD:
                continue
            value = field.process_element(
                element, prefix, getattr(cls, "__nsmap__", None)
            )
            if value is MISSING:
                if field.default is not MISSING or field.default_factory is not MISSING:
                    continue
                annotation = field._resolved_type()
                # Required collections naturally parse to empty containers.
                if field._is_iterable():
                    value = () if t.get_origin(annotation) is tuple else []
                else:
                    raise ValueError(f"Missing required XML field {field_name!r}")
            (constructor_dict if field.init else assignments)[field_name] = value

        instance = cls(**constructor_dict)
        for name, value in assignments.items():
            setattr(instance, name, value)
        instance.__attrib__ = dict(element.attrib)
        instance.__nsmap__ = dict(element.nsmap)
        return instance

    @classmethod
    def from_data(cls, data: bytes | str, prefix: str = "", **kwargs) -> t.Self:
        """Parse XML with lxml.etree.fromstring, forwarding parser options."""
        _class_tag(cls)
        root = ET.fromstring(data, **kwargs)
        return cls.from_lxml_element(root, prefix)
