# fix-llm-xml

**顺手的 LLM 生成 XML 修复工具**  
[![PyPI version](https://img.shields.io/pypi/v/fix-llm-xml)](https://pypi.org/project/fix-llm-xml/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> 您宝贵的词元（tokens）不会再被 XML 解析器偷吃啦！

`fix-llm-xml` 专门解决大语言模型（LLM）输出 XML 时经常出现的各种格式错误。

它可以优雅地处理未转义的特殊字符、标签不匹配、畸形 CDATA、缺失闭合标签等问题，并**保证指定纯文本标签内的内容完整**。

经过 **超过 100 个随机测试** 和大量现实场景验证，能够轻松应对 LLM 产出的各种损坏的 XML。

## 主要特性

- 🧩 **智能解析** – `parse_xml` 提供一键式修复+解析，直接解析失败时自动修复。
- 📃 **安全保留文本内容** – 对用户指定的纯文本标签（及 CDATA 内容），自动转义并保留原始文本内容，避免内容被误解析为 XML 结构。
- 🔧 **自动修复标签结构** – 补全缺失的闭合标签，丢弃多余的闭合标签；错误闭合时优先结束当前层，尽量保留后续内容。
- 📦 **CDATA 兼容处理** – 识别 CDATA 的标准及常见错误写法，规范输出 CDATA 段，安全处理内部 `]]>` 。
- 🧷 **属性自动修复** – 补全未闭合引号、为无引号属性值加引号、转义属性值特殊字符、删除重复属性。
- 🌍 **命名空间支持** – 支持带有命名空间前缀的标签（如 `ns:code`）。
- 🧪 **经过全面测试** – 结合传统单元测试与基于属性的随机测试，覆盖多种极端和损坏输入。
- 📁 **依赖精简** – 仅依赖 `lxml` 与 `xmltodict`，适合生产环境。

## 安装

```bash
pip install fix-llm-xml
```

## 快速开始

假设你的 LLM 返回了这样一段“不干净”的 XML：

```text
一些无关前缀文字
<result>
  <answer>if a < b && c > d</answer>
  <file name="a.html"><![CDATA[<!DOCTYPE html><html lang="en">...</html>]></file>
  <meta>
    <confidence>0.95</confidence>
</result>
```

用 `fix_llm_xml.parse_xml` 可以一键解析，输出 xmltodict 格式的字典：

```python
from fix_llm_xml import parse_xml

llm_output = '''
一些无关前缀文字
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

示例中 `answer` 按纯文本标签转义；`file` 因开始标签后紧跟 CDATA 起始前缀，即使未列入 `text_tags`，也会按 CDATA 内容保留。

## API 参考

### `parse_xml(s, root, text_tags=None, **kwargs)`

从杂乱字符串中提取、修复并解析 XML 为 Python 字典（**xmltodict** 格式）的一体化函数。
内部会先调用 `find_xml_document` 并尝试直接解析；如果 `text_tags` 中出现异常嵌套或直接解析失败，则调用 `fix_xml_with_text_tags` 修复后再解析。

**参数**：
- `s` (str): 输入的原始字符串。
- `root` (str): 期望的根标签名称。
- `text_tags` (Optional[List[str]]): 已知的**只包含纯文本**的标签列表，传递给 `fix_xml_with_text_tags`。
- `**kwargs`: 其他传递给 `xmltodict.parse` 的参数，常用选项如：
  - `force_list` (List[str]): 强制某些标签总是解析为列表（即使只有一个实例）。
  - `strip_whitespace` (bool): 默认 `True`，是否去除文本值首尾空白。

**返回值**：
- `Optional[Dict]`：解析后的字典；若所有修复尝试均失败则返回 `None`。

**示例**：
```python
text = """
aaaaa
<response>
  <data>
    <item id="1">苹果</item>
    <item id="2">橘子</item>
  </data>
  <status>成功
</response>
bbbbb
"""
result = fix_llm_xml.parse_xml(text, "response", force_list=["item"])
print(result)
# {
#   'response': {
#     'data': {
#       'item': [
#         {'@id': '1', '#text': '苹果'},
#         {'@id': '2', '#text': '橘子'}
#       ]
#     },
#     'status': '成功'
#   }
# }
```

### `find_xml_document(s, root, with_tag=False, cdata=False)`

从一段可能混杂了非 XML 文字的大字符串中提取 `<root>` 标签内的内容。
算法：从左往右找标签开头，从右往左找标签结尾。

**参数**：
- `s` (str): 输入字符串。
- `root` (str): 目标根标签的名称。
- `with_tag` (bool): 若为 `True`，返回结果包含开闭标签本身；若 `False`，只返回标签内部内容。
- `cdata` (bool): 若为 `True`，期望根标签后紧跟 `<![CDATA[...]]>` 包裹，返回 CDATA 内部的纯文本。

**返回值**：
- `Optional[str]`：提取到的内容字符串；若找不到目标标签则返回 `None`。

**示例**：
```python
s = "前言<root>核心内容</root>后语"
find_xml_document(s, "root")                 # 返回 "核心内容"
find_xml_document(s, "root", with_tag=True)  # 返回 "<root>核心内容</root>"
```


### `get_xml_tag_text(value)`

安全地从 `xmltodict` 解析结果中提取标签内的文本内容。可以处理各种可能的返回值格式（字符串、字典、列表等）。

**参数**：
- `value`：来自 `parse_xml` 结果字典中某个标签对应的值。

**返回值**：
- `str`：提取出的文本；
  - 若值为 `None` → 返回 `''`；
  - 若为字符串 → 直接返回；
  - 若为字典且含 `#text` 键 → 返回 `#text` 的值；
  - 若为列表 → 取第一个元素递归处理；
  - 其他情况 → 返回 `''`。

**示例**：
```python
parsed = {'tag': [{'#text': 'hello', '@attr': 'x'}]}
get_xml_tag_text(parsed['tag'])  # 返回 'hello'
```


### `fix_xml_with_text_tags(xml, text_tags=())`

修复损坏的 XML 字符串，使其成为结构合法、可被宽松 XML 解析器（如 lxml）处理的形式。
例如下游用户不想使用 xmltodict，则可以直接调用该函数修复。

**参数**：
- `xml` (str): 待修复的 XML 字符串。
- `text_tags` (Iterable[str]): 纯文本标签名称的可迭代对象（区分大小写，支持 `ns:tag` 形式）。这些标签被视为**只包含纯文本**，不会尝试解析内部子元素；其中未转义字符会被正确转义。

**返回值**：
- `str`：修复后的合法 XML 字符串。

**核心行为**：
- 自动闭合未关闭的普通标签，丢弃多余或无法匹配的闭合标签；错误闭合时尽量只结束当前层，避免吞掉后续内容。
- 修复开始标签属性：补全未闭合引号、为无引号属性值加双引号、清洗非法属性名、转义属性值中的特殊字符、重复属性保留第一个；结束标签中的属性全部删除。
- 对 `text_tags` 中的纯文本标签（且开始标签后没有 CDATA 起始前缀）：内容统一按普通 XML 文本转义；其中的 CDATA 写法只作为普通文本处理，不会切换为 CDATA 模式。
- 对开始标签后紧跟标准或错误 CDATA 起始前缀的标签：无论是否在 `text_tags` 中，都按 CDATA 内容处理；输出统一为标准 CDATA 段，内部 `]]>` 安全转义，清理正确或疑似 CDATA 结束符。
- 普通结构标签内的合法原生 CDATA 段保持不变。
- 合法的同名嵌套保持原样；缺失闭合导致的同名结构会尽量调整为并列节点，避免内容丢失。
- 输出为语法良构的 XML，不支持高级 XML 功能，修复后的 XML 可交给宽松解析器继续处理。

**示例**：
```python
malformed = "<root><code>if a < b && c > d</code></root>"
fixed = fix_xml_with_text_tags(malformed, ["code"])
print(fixed)
# <root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>
```

## 使用场景与基本假设

本库假设你的工作流如下：

1. 你向 LLM 发送提示，要求它用 **XML 格式** 返回结构化数据。
2. LLM 返回的文本中，除了 XML 还可能前后包含其他自然语言文字。
3. 你事先指定哪些标签是“**纯文本标签**”（例如 `<file>`、`<answer>`），或指示 LLM 将文本内容用 CDATA 包裹。
4. 你希望在不丢失**文本内容**的前提下，将这段输出合理地解析出来。

关于文本内容，请注意：

- 文本内容应将标签名用 `text_tags` 指定
- 长文本优先让 LLM 使用 CDATA 标签
- 不使用 CDATA 的文本标签内容不应包含未转义的 XML 标签

本库尤其擅长处理以下常见 LLM 输出错误：

- 特殊字符未转义：`1 < 2` 出现在普通文本标签中。
- CDATA 被错误书写：`<CDATA[`、`[CDATA[`、`]>` 等。
- 嵌套 XML 内容被错误地包裹进同一个标签。
- 标签忘记闭合，或者多写了闭合标签。
- 开始标签属性引号未关闭、属性值未加引号、属性名非法、属性重复，或结束标签带属性。

## 测试与质量保证

`fix-llm-xml` 经过了大量、多层次的测试，确保在各种极端和随机情况下都能正确工作。

- **常规单元测试**：覆盖基础功能、边界情况、文档示例，以及大量刻意构造的畸形 XML 样本。
- **基于属性的随机测试**：使用 [Hypothesis](https://hypothesis.readthedocs.io/) 生成大量随机、不平衡的 XML 片段，验证标签闭合、修复稳定性、纯文本内容可恢复等关键不变量。
- **复杂嵌套场景**：特别测试多层嵌套 CDATA、同名标签嵌套、CDATA 内包含与闭合标签相同的字符序列等容易混淆的情况。