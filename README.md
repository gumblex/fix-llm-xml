# fix-llm-xml

**Practical, ready-to-use tools for LLM generated XML**  
[![PyPI version](https://img.shields.io/pypi/v/fix-llm-xml)](https://pypi.org/project/fix-llm-xml/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[中文文档](./README.zh.md)

> Your precious tokens will not be eaten by XML parsers!

`fix-llm-xml` is specifically designed to solve common formatting errors that occur when Large Language Models (LLMs) output XML.

It gracefully handles unescaped special characters, mismatched tags, malformed CDATA, missing closing tags and more, while **guaranteeing full integrity of content inside specified plaintext tags**.

Validated by **over 100 random tests** and numerous real-world scenarios, it easily handles all kinds of corrupted XML produced by LLMs.

## Key Features

- 🧩 **Smart Parsing** – `parse_xml` provides one-click repair + parsing, automatically runs repair if the initial parse attempt fails.
- 📃 **Text Content Preservation** – Automatically escapes and retains original text content for user-specified plaintext tags (and CDATA content), preventing content from being misparsed as XML structures.
- 🔧 **Automatic Tag Structure Repair** – Completes missing closing tags, discards redundant closing tags; when mismatched closing tags are encountered, it prioritizes closing the current layer to preserve as much subsequent content as possible.
- 📦 **CDATA Compatibility Processing** – Recognizes both standard and common malformed CDATA syntax, standardizes CDATA section output, and safely handles internal `]]>` sequences.
- 🧷 **Automatic Attribute Repair** – Completes unclosed quotes, adds quotes to unquoted attribute values, escapes special characters in attribute values, and removes duplicate attributes.
- 🌍 **Namespace Support** – Supports tags with namespace prefixes (e.g. `ns:code`).
- 🧪 **Comprehensively Tested** – Combines traditional unit testing with property-based random testing to cover a wide range of extreme and corrupted input scenarios.
- 📁 **Minimal Dependencies** – Only depends on `lxml` and `xmltodict`, suitable for production environments.

## Installation

```bash
pip install fix-llm-xml
```

## Quick Start

Suppose your LLM returns the following "unclean" XML:

```text
Some irrelevant prefix text
<result>
  <answer>if a < b && c > d</answer>
  <file name="a.html"><![CDATA[<!DOCTYPE html><html lang="en">...</html>]></file>
  <meta>
    <confidence>0.95</confidence>
</result>
```

Use `fix_llm_xml.parse_xml` to parse it in one click, outputting a dictionary in xmltodict format:

```python
from fix_llm_xml import parse_xml

llm_output = '''
Some irrelevant prefix text
<result>
  <answer>if a < b && c > d</answer>
  <file name="a.html"><![CDATA[<!DOCTYPE html><html lang="en">...</html>]></file>
  <meta>
    <confidence>0.95</confidence>
</result>
'''

parsed = parse_xml(llm_output, root="result", text_tags=["answer"])
print(parsed)
# {'result': {'answer': 'if a < b && c > d', 'file': {'@name': 'a.html', '#text': '<!DOCTYPE html><html lang="en">...</html>'}, 'meta': {'confidence': '0.95'}}}
```

In this example, the `answer` tag is treated as a plaintext tag and its content is properly escaped. The `file` tag retains its content as CDATA even though it is not included in the `text_tags` list, as it is immediately followed by a CDATA opening prefix.

## API Reference

### `parse_xml(s, root, text_tags=None, **kwargs)`

All-in-one function to extract, repair, and parse XML from messy strings into Python dictionaries (**xmltodict** format).
Internally, it first calls `find_xml_document` and attempts direct parsing. If abnormal nesting is detected in `text_tags` or direct parsing fails, it invokes `fix_xml_with_text_tags` to repair the content before re-parsing.

**Parameters**:
- `s` (str): Original input string.
- `root` (str): Expected root tag name.
- `text_tags` (Optional[List[str]]): List of known tags that **contain only plaintext content**, passed to `fix_xml_with_text_tags`.
- `**kwargs`: Additional parameters passed to `xmltodict.parse`, common options include:
  - `force_list` (List[str]): Force specified tags to always be parsed as lists (even if only one instance exists).
  - `strip_whitespace` (bool): Default `True`, whether to strip leading/trailing whitespace from text values.

**Return Value**:
- `Optional[Dict]`: Parsed dictionary; returns `None` if all repair attempts fail.

**Example**:
```python
text = """
aaaaa
<response>
  <data>
    <item id="1">Apple</item>
    <item id="2">Orange</item>
  </data>
  <status>Success
</response>
bbbbb
"""
result = fix_llm_xml.parse_xml(text, "response", force_list=["item"])
print(result)
# {
#   'response': {
#     'data': {
#       'item': [
#         {'@id': '1', '#text': 'Apple'},
#         {'@id': '2', '#text': 'Orange'}
#       ]
#     },
#     'status': 'Success'
#   }
# }
```

### `find_xml_document(s, root, with_tag=False, cdata=False)`

Extracts content inside `<root>` tags from a large string that may be mixed with non-XML text.
Algorithm: Finds the opening tag from left to right, finds the closing tag from right to left.

**Parameters**:
- `s` (str): Input string.
- `root` (str): Name of the target root tag.
- `with_tag` (bool): If `True`, returned result includes the opening and closing tags themselves; if `False`, only returns content inside the tags.
- `cdata` (bool): If `True`, expects the root tag to be immediately followed by `<![CDATA[...]]>` wrapping, returns plain text inside CDATA.

**Return Value**:
- `Optional[str]`: Extracted content string; returns `None` if target tag cannot be found.

**Example**:
```python
s = "Prefix text<root>Core content</root>Suffix text"
find_xml_document(s, "root")                 # Returns "Core content"
find_xml_document(s, "root", with_tag=True)  # Returns "<root>Core content</root>"
```


### `get_xml_tag_text(value)`

Safely extracts text content inside tags from `xmltodict` parsing results. Handles all possible return value formats (strings, dictionaries, lists, etc.).

**Parameters**:
- `value`: Value corresponding to a tag from the `parse_xml` result dictionary.

**Return Value**:
- `str`: Extracted text;
  - If value is `None` → returns `''`;
  - If it is a string → returns directly;
  - If it is a dictionary with `#text` key → returns value of `#text`;
  - If it is a list → takes first element and processes recursively;
  - Other cases → returns `''`.

**Example**:
```python
parsed = {'tag': [{'#text': 'hello', '@attr': 'x'}]}
get_xml_tag_text(parsed['tag'])  # Returns 'hello'
```


### `fix_xml_with_text_tags(xml, text_tags=())`

Repairs corrupted XML strings to make them structurally valid and processable by lenient XML parsers (such as lxml).
For example, if downstream users do not want to use xmltodict, they can directly call this function for repair.

**Parameters**:
- `xml` (str): XML string to be repaired.
- `text_tags` (Iterable[str]): Iterable of plaintext tag names (case-sensitive, supports `ns:tag` format). These tags are considered to contain **only plain text content**, no internal child elements will be parsed; unescaped special characters in the content will be properly handled.

**Return Value**:
- `str`: Valid XML string after repair.

**Core Behaviors**:
- Automatically closes unclosed regular tags, discards redundant or mismatched closing tags; when mismatched closing tags are encountered, it prioritizes closing the current layer to avoid swallowing subsequent content.
- Repairs start tag attributes: completes unclosed quotes, adds double quotes to unquoted attribute values, cleans illegal attribute names, escapes special characters in attribute values, keeps the first occurrence of duplicate attributes, and strips all attributes from end tags.
- For plaintext tags listed in `text_tags` (that are not immediately followed by a CDATA opening prefix): content is escaped as standard XML text; any malformed CDATA syntax inside is treated as regular text, and will not switch to CDATA parsing mode.
- For any tag that is immediately followed by a standard or malformed CDATA opening prefix: its content is processed as CDATA regardless of whether it is listed in `text_tags`. Output is standardized as proper CDATA sections, internal `]]>` sequences are safely escaped, and valid or suspected CDATA end markers are properly cleaned.
- Valid native CDATA sections inside regular structural tags are preserved unchanged.
- Valid same-name nested tag structures are kept as-is; for same-name structures caused by missing closing tags, they are adjusted to parallel nodes as much as possible to avoid content loss.
- The output is syntactically well-formed XML, does not support advanced XML features, and can be passed to a lenient parser for further processing.

**Example**:
```python
malformed = "<root><code>if a < b && c > d</code></root>"
fixed = fix_xml_with_text_tags(malformed, ["code"])
print(fixed)
# <root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>
```

## Usage Scenarios and Basic Assumptions

This library assumes your workflow is as follows:

1. You send a prompt to an LLM, requiring it to return structured data in **XML format**.
2. The text returned by the LLM may contain other natural language text before and after the XML.
3. You specify in advance which tags are "**plaintext tags**" (e.g. `<file>`, `<answer>`), or instruct the LLM to wrap text content in CDATA.
4. You want to reasonably parse this output **without losing any text content**.

Guidelines for handling plaintext content:
- Tags containing plaintext content should be declared in the `text_tags` list.
- Long text content is best requested to be wrapped by LLMs in CDATA tags.
- Plaintext tags without CDATA wrapping should not contain unescaped XML tags in their content.

This library is especially good at handling the following common LLM output errors:

- Unescaped special characters: `1 < 2` appears in regular text tags.
- Incorrectly written CDATA: `<CDATA[`, `[CDATA[`, `]>` etc.
- Nested XML content is incorrectly wrapped into the same tag.
- Missing closing tags, or extra redundant closing tags.
- Unclosed quotes in start tag attributes, unquoted attribute values, illegal attribute names, duplicate attributes, or attributes attached to end tags.


## Testing and Quality Assurance

`fix-llm-xml` has passed a large number of multi-level tests to ensure correct operation under various extreme and random conditions.

- **Conventional Unit Tests**: Covers basic functionality, edge cases, documentation examples, and a large set of deliberately constructed malformed XML samples.
- **Property-based Random Testing**: Uses [Hypothesis](https://hypothesis.readthedocs.io/) to generate a large number of random, unbalanced XML fragments to verify key invariants such as proper tag closure, repair stability, and recoverability of plaintext tag content.
- **Complex Nested Scenarios**: Specifically tests easily confusing edge cases including multi-level nested CDATA, same-name nested tags, and CDATA sections containing character sequences identical to closing tags.
