# fix-llm-xml

**Practical, ready-to-use tools for LLM generated XML**  
[![PyPI version](https://img.shields.io/pypi/v/fix-llm-xml)](https://pypi.org/project/fix-llm-xml/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[中文文档](./README.zh.md)

`fix-llm-xml` is specifically designed to solve common formatting errors that occur when Large Language Models (LLMs) output XML.  
It gracefully handles unescaped special characters, mismatched tags, malformed CDATA, missing closing tags and more, while **guaranteeing full integrity of content inside plaintext tags**.

Validated by **over 100 random tests** and numerous real-world scenarios, it easily handles all kinds of corrupted XML produced by LLMs.

## Key Features

- 🧩 **Smart Parsing** – `parse_xml` provides one-click repair + parsing, automatically repair if the first attempt fails.
- 🛡️ **Text Content Preservation** – Automatically escapes and retains original content for user-specified plaintext tags (and CDATA content), preventing data loss during automatic repair.
- 🔧 **Automatic Tag Structure Repair** – Completes missing closing tags, discards redundant closing tags.
- 📦 **Deep CDATA Repair** – Handles nested CDATA, malformed CDATA prefixes, incorrect CDATA closing formats, and automatically escapes internal `]]>` to a safe form.
- 🌍 **Namespace Support** – Supports tags with namespace prefixes (e.g. `ns:code`).
- 🧪 **Comprehensively Tested** – Combines traditional unit testing with Hypothesis property-based random testing to verify correctness under all kinds of extreme conditions.
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

parsed = parse_xml(llm_output, root="result")
print(parsed)
# {'result': {'answer': 'if a < b && c > d', 'file': {'@name': 'a.html', '#text': '<!DOCTYPE html><html lang="en">...</html>'}}}
```

## API Reference

### `parse_xml(s, root, text_tags=None, **kwargs)`

All-in-one function to extract, repair, and parse XML from messy strings into Python dictionaries (**xmltodict** format).
Internally it first calls `find_xml_document` and parses with `xmltodict`; if direct parsing fails, it calls `fix_xml_with_text_tags` + lxml repair for a second parsing attempt.

**Parameters**:
- `s` (str): Original input string.
- `root` (str): Expected root tag name.
- `text_tags` (Optional[List[str]]): List of known plaintext tags, passed to `fix_xml_with_text_tags`.
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
- `text_tags` (Iterable[str]): Iterable of plaintext tag names (case-sensitive, supports `ns:tag` format). These tags are considered to contain only plain text, no internal child elements will be parsed; characters such as `<`, `>`, `&` inside will be properly escaped, or protected via CDATA.

**Return Value**:
- `str`: Valid XML string after repair.

**Core Behaviors**:
- Automatically closes unclosed regular tags, deletes redundant closing tags.
- Automatically escapes text, will not re-escape already escaped content.
- For plaintext tags (listed in text_tags, or wrapped with CDATA):
  - Automatically detects CDATA usage (including malformed CDATA prefixes/suffixes) and standardizes it.
  - In CDATA mode, escapes nested `]]>` to `]]]]><![CDATA[>`; will not re-escape already escaped content.
  - In normal mode, escapes `<`, `>`, `&` to corresponding XML entities; will not re-escape already escaped entities.
- Retains all attributes, comments, self-closing tags.
- Does not guarantee 100% compliance with XML specifications, does not support advanced XML features; output may still have logical issues, requires re-parsing by a lenient XML parser.

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
3. You know in advance which tags are "plaintext tags" (e.g. `<file>`, `<answer>`), or instruct the LLM to wrap text content in CDATA. The content of these tags should not be parsed as XML child elements, but as complete plaintext/code snippets.
4. You want to reasonably parse this output **without losing any text content**.

This library provides a complete set of tools for the above process, especially good at handling the following common LLM output errors:

- Unescaped special characters: `1 < 2` appears in regular text tags.
- Incorrectly written CDATA: `<CDATA[`, `[CDATA[`, `]>` etc.
- Nested XML content is incorrectly wrapped into the same tag.
- Missing closing tags, or extra redundant closing tags.


## Testing and Quality Assurance

`fix-llm-xml` has passed a large number of multi-level tests to ensure correct operation under various extreme and random conditions.

- **Conventional Unit Tests**: Covers basic functions, edge cases, examples in documentation, and nearly a hundred deliberately constructed malformed XML samples.
- **Property-based Random Testing**: Uses [Hypothesis](https://hypothesis.readthedocs.io/) to generate a large number of random, unbalanced XML fragments to verify the following invariants:
  - All tags in the repaired XML are properly closed.
  - The result remains unchanged after re-repairing already repaired XML.
  - Original content inside plaintext tags can be fully recovered after repair.
  - The escape function will not introduce unescaped special characters, nor will it perform secondary escaping.
- **Complex Nested Scenarios**: Specifically tested for easily confusing cases such as multi-level nested CDATA, nested tags with the same name, CDATA containing character sequences identical to closing tags, etc.
