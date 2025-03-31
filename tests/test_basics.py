import lxml.etree as ET

from src.lxml_dataclass import Element, element_field


class Author(Element):
    __tag__ = "Author"

    name: str = element_field("Name")
    last: str = element_field("LastName", default="Doe")

    def fullname(self) -> str:
        return f"{self.name} {self.last}"


def test_element():
    a = Author("name", "lastname")
    b = Author("name")

    assert a.fullname() == "name lastname"
    assert b.fullname() == "name Doe"


def test_to_lxml_element():
    a = Author("name", "lastname")
    a_element = a.to_lxml_element()
    assert isinstance(a_element, ET._Element)


def test_to_string_element():
    a = Author("name", "lastname")
    assert (
        a.to_string_element()
        == b"<Author><Name>name</Name><LastName>lastname</LastName></Author>"
    )
    assert (
        a.to_string_element(pretty_print=True)
        == b"<Author>\n  <Name>name</Name>\n  <LastName>lastname</LastName>\n</Author>\n"
    )
