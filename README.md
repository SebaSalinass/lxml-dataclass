# LXML-DATACLASS

Utility to mirror Python Classes with lxml.etree Elements using class annotations and field descriptors.

```
⚠️ Warning: this package was created to help the owner with big xml file description and manipulation.
Use under your own risk. 
```

```
🆘 Help wanted. If you are insterested in continue the development of this package, send me a PM.
```

## Installation

```bash
pip install lxml-dataclass
```

## Basic usage

Lxml-dataclass uses big part of dataclasses implementation with some modifications that allow the implemmentation of two utility methods to the classes that inherit from `Element` base class `to_lxml_element` and `from_lxml_element`. Using the `element_field` function allows the metaclass to keep tracking of many lxml.etree attributes. 

Lets start with some basic examples:

```python
from lxml_dataclass import Element, element_field


class Author(Element):
    __tag__ = 'Author'
    
    name: str = element_field('Name')
    last: str = element_field('LastName', default='Doe')

    def fullname(self) -> str:
        return self.name + self.last

author = Author('John')
author.fullname()
# John Doe
```

As you can see in the given example we defined a class called `Author` with the attributes `name` and `last` as you can see these attributes where defined with their respectives types annotations and the field descriptor function `element_field` this functions accepts almost the same arguments the original dataclass `field` function uses except you must give as first argument the tag name the given attribute. The init method is automatically generated and you can overload it.

In the example above the tag for `name` will be `Name` and for `last` will be `LastName`

Now we will call the `to_lxml_element()` method to obtain the `lxml.etree.Element` representing this object

```python
import lxml.etree as ET

author_element = author.to_lxml_element() 
ET.tostring(author_element)
# b'<Author><Name>John</Name><LastName>Doe</LastName></Author>'
```

The Element class also includes another utility method called `to_string_element()` which calls the `ET.tostring()` function on the representing element and accepts the same keyword arguments. 

```python
author.to_string_element(pretty_print=True).decode('utf-8')
#<Author>
#  <Name>John</Name>
#  <LastName>Doe</LastName>
#</Author>
```

## Attribs and Nsmap
As you know all lxml Element accetps the `attrib` and `nsmap` arguments.
For Element classes you will define those attributes on `__attrib__` and `__nsmap__` class or instance attributes and for class attributes you will define them on the `element_field` method with the `attrib` and `nsmap` key word arguments. 

Lets add some attributes:

```python
class Author(Element):
    __tag__ = 'Author'
    __attrib__ = {'ID': 'Test ID'}
    
    name: str = element_field('Name', nsmap={None: 'suffix'})
    last: str = element_field('LastName', default='Doe')
```
Before we get the element string we will change the ID attribute.

```bash python
author.__attrib__['ID'] = 'Changed ID'
author.to_string_element(pretty_print=True).decode('utf-8')
#<Author ID="Changed ID">
#  <Name xmlns="suffix">John</Name>
#  <LastName>Doe</LastName>
#</Author>
```

# Class inheritance and composition

Inheritance functions exactly the same as dataclasses so you can inherit from other `Element` classes within the rules of dataclass and init generation.

Lets create an Element mixin that will add an ID to every instance who inherit it.

```python
from uuid import UUID, uuid4

class HasIDMixin(Element):

    id: UUID = element_field('Id', default_factory=uuid4)


class Author(HasIdMixin, Element):
    __tag__ = 'Author'
    
    name: str = element_field('Name')
    last: str = element_field('LastName', default='Doe')
```

```python
author = Author('John', 'Mayer')
author.to_string_element(pretty_print=True).decode('utf-8')
#<Author>
#  <Name>John</Name>
#  <LastName>Mayer</LastName>
#  <Id>a6ff6e02-eeb7-4ca5-8e4d-efedc40ee9ae</Id>
#</Author>
```

Now lets create a book element that will be a child of author

```python

class Book(Element):
    __tag__ = 'Book'

    name: str = element_field('Name')
    pages: int = element_field('Pages', default=50)


class Author(Element):
    __tag__ = 'Author'
    
    name: str = element_field('Name')
    last: str = element_field('LastName', default='Doe')
    book: Book | None = element_field('book', default=None) # Notice the tag is the same as the attribute name
```
```python
author = Author('John')
book = Book('My cool book', 80)
author.book = book
author.to_string_element(pretty_print=True).decode('utf-8')
#<Author>
#  <Name>John</Name>
#  <LastName>Doe</LastName>
#  <Book>
#    <Name>My cool book</Name>
#    <Pages>80</Pages>
#  </Book>
#</Author>
```

Now what if we want an Author to have multiple Books. Then we stablish the `is_iterable` special keyword on `element_field` function as follows

```python
class Author(Element):
    __tag__ = 'Author'
    
    name: str = element_field('Name')
    last: str = element_field('LastName', default='Doe')
    books: list[Book] = element_field('books', default_factory=list, is_iterable=True) # Notice the tag is the same as the attribute name

```
Now you could do 

```python
author = Author('John')
book_a = Book('My cool book A', 80)
book_b = Book('My cool book B')
author.books.append(book_a)
author.books.append(book_b)
author.to_string_element(pretty_print=True).decode('utf-8')
#<Author>
#  <Name>John</Name>
#  <LastName>Doe</LastName>
#  <Book>
#    <Name>My cool book A</Name>
#    <Pages>80</Pages>
#  </Book>
#  <Book>
#    <Name>My cool book B</Name>
#    <Pages>50</Pages>
#  </Book>
#</Author>
```

Now you can create really complex xml-class-representations with a simple and known dataclass approach, you can overload the utility methods to suit your needs.










