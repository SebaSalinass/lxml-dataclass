import lxml.etree as ET  # type: ignore
import sys
import types
import re
import typing as t

__all__ = ("Element", "element_field")


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


class InitVar:
    __slots__ = ("type",)

    def __init__(self, type):
        self.type = type

    def __repr__(self):
        if isinstance(self.type, type):
            type_name = self.type.__name__
        else:
            # typing objects, e.g. List[int]
            type_name = repr(self.type)
        return f"dataclasses.InitVar[{type_name}]"

    def __class_getitem__(cls, type):
        return InitVar(type)


# Field and Field Descriptors.
class ElementField:
    __slots__ = (
        "name",
        "type",
        "tag",
        "attrib",
        "nsmap",
        "display_empty",
        "validators",
        "format_spec",
        "is_iterable",
        "compare",
        "default",
        "default_factory",
        "coerce",
        "init",
        "kw_only",
        "_field_type",
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

    def _element_from_value(self, value):
        if isinstance(value, Element):
            return value.to_lxml_element()

        element = ET.Element(self.tag, self.attrib, self.nsmap)
        if value not in [MISSING, None]:
            element.text = (
                format(value, self.format_spec) if self.format_spec else str(value)
            )
        return element

    def process_value(self, value):
        if self.is_iterable:
            elements = []
            for inner_value in value:
                elements.append(self._element_from_value(inner_value))
            return elements
        return self._element_from_value(value)

    def _value_from_element(self, element):
        if issubclass(self.coerce.__class__, (ElementMeta, Element)):
            return self.coerce.from_lxml_element(element)
        return self.coerce(element.text) if element.text is not None else None

    def process_element(self, element):
        tag = self.tag if self.tag != self.name else self.coerce.__tag__

        if self.is_iterable:
            values = []
            for inner_element in element.findall(tag, self.nsmap):
                values.append(self._value_from_element(inner_element))
            return values

        field_element = element.find(tag, self.nsmap)
        if field_element is not None:
            return self._value_from_element(field_element)


def element_field(
    tag: str,
    *,
    attrib=None,
    nsmap=None,
    display_empty=False,
    validators=None,
    format_spec=None,
    is_iterable=False,
    compare=True,
    default=MISSING,
    default_factory=MISSING,
    coerce=None,
    init=True,
    kw_only=False,
):
    """_summary_

    Args:
        tag (str): The XML tag for this attribute. <tag>value</tag>
        attrib (dict, optional): An attributes dictionary is passed as attrib argument on Element creation. Defaults to None.
        nsmap (dict, optional): An NameSpaceMap dictionary is passed as nsmap argument on Element creation.. Defaults to None.
        display_empty (bool): Allows the Element creation without value </ tag>. Defaults to False.
        validators (Callable[[field, value], None], optional): A list of field, value validators called at __setattr__ should raise an error if value is not valid. Defaults to None.
        format_spec (str, optional): Format spec if needed for the value representation (datetimes, floats, etc). Defaults to None.
        is_iterable (bool, optional): Allows list detection when attr is another Element type. Defaults to False.
        compare (bool, optional): Allow this attribute to be check upon equal comparison. Defaults to True.
        default (Any, optional): Default value for the attribute. Defaults to MISSING.
        default_factory (Callable[[], Any], optional): A callable default factory. Defaults to MISSING.
        coerce (Callable[[str], Any], optional): Called on `Element.from_lxml_element(element)` data parsing from an already created ET.Element.  Defaults to None.
        init (bool, optional): Same as dataclasses behavior. Defaults to True.
        kw_only (bool, optional): Same as dataclasses behavior. Defaults to False.

    Returns:
        ElementField: Element field descriptor used to transform class into ET.Element and parsing from it.
    """
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


# Type Checkers
def _is_classvar(a_type, typing):
    # This test uses a typing internal class, but it's the best way to
    # test if this is a ClassVar.
    return a_type is typing.ClassVar or (
        type(a_type) is typing._GenericAlias and a_type.__origin__ is typing.ClassVar
    )


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


def _is_iterable_or_tuple(annotation, typing):
    return typing.get_origin(annotation) in [tuple, list]


def _default_coerce(annotation, typing):
    origin = typing.get_origin(annotation)

    if origin:
        return typing.get_args(annotation)[0]
    else:
        return annotation


# Field generation
def _get_field(cls, a_name, a_type, default_kw_only, typing=None):
    default = getattr(cls, a_name, MISSING)

    if isinstance(default, ElementField):
        f = default
    else:
        if isinstance(default, types.MemberDescriptorType):
            default = MISSING
        f = element_field(a_name, default=default)

    f.name = a_name
    f.type = a_type
    f._field_type = _FIELD

    if typing:
        if _is_classvar(a_type, typing) or (
            isinstance(f.type, str)
            and _is_type(f.type, cls, typing, typing.ClassVar, _is_classvar)
        ):
            f._field_type = _FIELD_CLASSVAR

        f.is_iterable = _is_iterable_or_tuple(a_type, typing)
        f.coerce = f.coerce or _default_coerce(a_type, typing)

    # If the type is InitVar, or if it's a matching string annotation,
    # then it's an InitVar.
    if f._field_type is _FIELD:
        # The module we're checking against is the module we're
        # currently in (dataclasses.py).
        module = sys.modules[__name__]
        if _is_initvar(a_type, module) or (
            isinstance(f.type, str)
            and _is_type(f.type, cls, module, module.InitVar, _is_initvar)
        ):
            f._field_type = _FIELD_INITVAR

    # Validations for individual fields.  This is delayed until now,
    # instead of in the Field() constructor, since only here do we
    # know the field name, which allows for better error reporting.

    # Special restrictions for ClassVar and InitVar.
    if f._field_type in (_FIELD_CLASSVAR, _FIELD_INITVAR):
        if f.default_factory is not MISSING:
            raise TypeError(f"field {f.name} cannot have a " "default factory")
        # Should I check for other field settings? default_factory
        # seems the most serious to check for.  Maybe add others.  For
        # example, how about init=False (or really,
        # init=<not-the-default-init-value>)?  It makes no sense for
        # ClassVar and InitVar to specify init=<anything>.

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
            raise TypeError(f"field {f.name} is a ClassVar but specifies " "kw_only")

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


# Function Genration
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
                f"{default_name}() "
                f"if {f.name} is _HAS_DEFAULT_FACTORY "
                f"else {f.name}"
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
        else:
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
    exec(txt, globals, ns)
    return ns["__create_fn__"](**locals)


def _tuple_str(obj_name, fields):
    # Return a string representing each field of obj_name as a tuple
    # member.  So, if fields is ['x', 'y'] and obj_name is "self",
    # return "(self.x,self.y)".

    # Special case for the 0-tuple.
    if not fields:
        return "()"
    # Note the trailing comma, needed if this turns out to be a 1-tuple.
    return f'({",".join([f"{obj_name}.{f.name}" for f in fields])},)'


def _init_fn(
    fields,
    std_fields,
    kw_only_fields,
    self_name,
    globals,
):
    seen_default = False

    for f in std_fields:
        if f.init:
            if not (f.default is MISSING and f.default_factory is MISSING):
                seen_default = True
            elif seen_default:
                raise TypeError(
                    f"non-default argument {f.name!r} " "follows default argument"
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
def _process_class(cls, kw_only: bool = False):
    fields = {}

    if cls.__module__ in sys.modules:
        globals = sys.modules[cls.__module__].__dict__
    else:
        globals = {}

    cls_annotations = cls.__dict__.get("__annotations__", {})
    cls_fields = []

    typing = sys.modules.get("typing")

    for f_name, f_type in cls_annotations.items():
        cls_fields.append(_get_field(cls, f_name, f_type, kw_only, typing))

    for f in cls_fields:
        fields[f.name] = f
        if f.name and isinstance(getattr(cls, f.name, None), ElementField):
            setattr(cls, f.name, f)

    for name, value in cls.__dict__.items():
        if isinstance(value, ElementField) and name not in cls_annotations:
            raise TypeError(f"{name!r} is a field but has no type annotation")

    for b in cls.__mro__[-1:0:-1]:
        # Only process classes that have been processed by our
        # decorator.  That is, they have a _FIELDS attribute.
        base_fields = getattr(b, _FIELDS, None)
        if base_fields is not None:
            for f in base_fields.values():
                fields[f.name] = f

    setattr(cls, _FIELDS, fields)

    all_init_fields = [f for f in fields.values()]

    (std_init_fields, kw_only_init_fields) = _fields_in_init_order(all_init_fields)

    _set_new_attribute(
        cls,
        "__init__",
        _init_fn(
            all_init_fields,
            std_init_fields,
            kw_only_init_fields,
            "__dataclass_self__" if "self" in fields else "self",
            globals,
        ),
    )

    # Create __eq__ method.  There's no need for a __ne__ method,
    # since python will call __eq__ and negate it.
    field_list = [f for f in fields.values() if f._field_type is _FIELD]
    flds = [f for f in field_list if f.compare]
    self_tuple = _tuple_str("self", flds)
    other_tuple = _tuple_str("other", flds)
    _set_new_attribute(
        cls, "__eq__", _cmp_fn("__eq__", "==", self_tuple, other_tuple, globals=globals)
    )

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
        class_ = super(ElementMeta, cls).__new__(cls, name, bases, namespace)
        processed_class = _process_class(class_, kw_only)

        return processed_class


# Usable Element Class
class Element(metaclass=ElementMeta):
    """The base Element class allows xml representation through lxml implementation

    >>> class Author(Element):
    >>>     __tag__ = 'Author'

    >>>     name: str = element_field('Name')
    >>>     last: str = element_field('LastName', default='Doe')
    """

    def __setattr__(self, __name, __value):
        fields = getattr(self.__class__, _FIELDS, {})

        if field := fields.get(__name):
            field.validate_value(__value)
        object.__setattr__(self, __name, __value)

    def to_lxml_element(self) -> ET._Element:
        tag = getattr(self.__class__, "__tag__", None)

        if not tag:
            raise AttributeError("You must define __tag__ class attribute")

        attrib = getattr(self, "__attrib__", None)
        nsmap = getattr(self, "__nsmap__", None)

        root = ET.Element(tag, attrib, nsmap)
        fields = getattr(self.__class__, _FIELDS, {})
        ignored_fields = getattr(self.__class__, _IGNORED_FIELDS, [])

        for field_name, element_field in fields.items():
            if field_name in ignored_fields:
                continue

            value = getattr(self, field_name, None)
            if not value and not element_field.display_empty:
                continue

            root_operation = root.extend if element_field.is_iterable else root.append
            root_operation(element_field.process_value(value))

        return root

    def to_string_element(self, **kwargs) -> bytes:
        return ET.tostring(self.to_lxml_element(), **kwargs)

    @classmethod
    def from_lxml_element(cls, element: ET._Element) -> t.Self:
        constructor_dict = {}

        fields = getattr(cls, _FIELDS, {})
        ignored_fields = getattr(cls, _IGNORED_FIELDS, [])

        for field in ignored_fields:
            fields.pop(field, None)

        for field_name, element_field in fields.items():
            value = element_field.process_element(element)
            constructor_dict[field_name] = value

        return cls(**constructor_dict)

    @classmethod
    def from_data(cls, data: bytes, **kwargs) -> t.Self:
        tag = getattr(cls, "__tag__")

        if not tag:
            raise AttributeError("You must define __tag__ class attribute")

        root = ET.fromstring(data, **kwargs)
        if not root.tag == tag:
            raise TypeError(
                f"The given data root tag is not equal to this class tag data_tag={root.tag}, class_tag{tag}"
            )
        return cls.from_lxml_element(root)
