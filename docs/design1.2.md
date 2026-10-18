# `fix-llm-xml` 容错解析设计文档

## 1. 背景与目标

LLM 生成 XML 时，关闭标签相关问题非常常见：

- 漏掉 `]]>`，或把 `]]>` 写错；
- 使用了错误的关闭标签，例如  
  `<root><result>aaa</answer><result>bbb</result></root>`；
- 某一层没有正确关闭，但后面仍然继续输出有效的开始/关闭标签；
- text_tag 内包含未转义的特殊字符、同名标签、外来标签；
- CDATA 起始写法不规范，或 CDATA 结束符缺失/错误；
- 标签属性存在书写错误，如未关闭引号、未加引号、重复属性名、非法属性字符等。

本设计的目标是：

1. **正确 XML 不修复**：合法 XML 走快速路径直接解析，不触发结构修复。
2. **错误 XML 尽量“多节点、浅深度”**：避免最后一个错误节点吞掉后续全部 XML 内容。错误关闭、缺失关闭应尽量体现为当前层结束，并让后续标签成为兄弟节点或更浅层节点。
3. **保持 text_tags 语义**：text_tags 内的错误关闭仍要处理；text_tags 中真正的同名/上级标签文本必须已经转义，或放在 CDATA 中。
4. **同名嵌套作为“可能漏关闭”的信号**：合法同名嵌套不拆；只有被隐式关闭的外层节点才参与同名拆分。
5. **CDATA 起始标签特殊处理**：  
   `<tag><![CDATA[` 或其他兼容 CDATA 起始写法作为一个整体处理。  
   这类标签关闭时先查找精确组合关闭 `]]></tag>`，其次查找疑似 `]]>` + `</tag>`，再次按 text_tags 规则查找关闭标签；关闭后删除正确或疑似写错的 `]]>`。  
   带 CDATA 起始的标签不再判断 `text_tags` 名单，直接适用 text_tags 的关闭规则。
6. **标签属性自动修复** – 自动纠正LLM生成标签时出现的各类属性书写错误，保证输出XML的属性语法良构，同时尽可能完整保留原始属性的语义与内容。
7. **修复过程不调用 XML parser**：  
   修复算法只做字符串扫描、树构造和序列化，保证输出语法良构。  
   XML parser 只在解析入口和出口出现，用于语义解析与最终兜底。
8. **复杂度可控**：主流程单次建树，不采用多候选树打分；`parse_xml` 最多保留“直接解析”和“修复后解析”两条路径。


## 2. 核心术语

- **结构模式**：按 XML 标签栈处理普通开始/关闭/自闭合/注释。
- **文本标签**：内容应作为纯文本处理的标签，分为两类，处理规则完全独立：
  1. **纯文本标签**：标签名在 `text_tags` 中，且开始标签后未紧跟兼容CDATA起始前缀。这类标签的所有内容统一走普通XML实体转义，不支持内容中途嵌入CDATA段；
  2. **CDATA 起始标签**：开始标签后紧跟兼容 CDATA 起始前缀，形成独立处理单元。这类标签无论名称是否在 `text_tags` 名单中，全程采用CDATA模式处理内容。
- **CDATA 起始标签**：开始标签与紧随其后的 CDATA 兼容前缀视为整体，例如 `<file><![CDATA[`、`<file><CDATA[`、`<file>[CDATA[` 等。其名称不必出现在 `text_tags` 中。
- **显式关闭**：节点由自己的 `</name>` 正常关闭。
- **隐式关闭**：节点由上级关闭、错误关闭标签、EOF、文本标签边界、CDATA fallback 等提前关闭。
- **关闭前瞻**：判断当前节点未来是否还能在任意上级关闭之前，被自己的 `</name>` 正常关闭。用于决定错误关闭标签或外来标签是“可能写错”还是“当前层应结束”的信号。
- **同名拆分**：对隐式关闭的节点，如果内部出现同名子节点，则在该同名子节点处拆分，把外层节点和后续内容提升为兄弟节点。
- **标准化属性**：经过语法修复、格式统一、错误纠正后的合法XML属性键值对。


## 3. 数据结构

### 3.1 Token

一次扫描得到 token 流：

```python
(kind, name, start, end)
# kind ∈ {"start", "end", "self_close", "comment"}
```

同时建立两个索引：

```python
opens_of[name]  = 所有该名字 start token 的升序索引
closes_of[name] = 所有该名字 end token 的升序索引
```

用于 O(log n) 查询某个位置之后最近的 `</name>`。

### 3.2 Node

```python
class Node:
    name: str
    start_tag: str              # 原始开始标签完整字符串
    attrs: Dict[str, str]       # 修复后的标准化属性键值对
    parent: Node | None
    children: list              # Node 或 TextSegment

    is_text_tag: bool           # 是否文本标签
    cdata_start: bool           # 是否 CDATA 起始标签
    cdata_open_prefix: str      # 原始 CDATA 起始前缀，如 <![CDATA[
    content_pos: int            # 文本标签当前内容扫描位置
    in_cdata: bool              # 当前是否处于 CDATA 内容中（仅对CDATA起始标签节点、结构模式下的原生CDATA块为True，纯文本标签恒为False）
    segments: list              # 文本标签内容段

    explicit_close: bool        # 是否由自己的 </name> 关闭
    auto_closed: bool           # 是否被隐式关闭
```

### 3.3 TextSegment

```python
class TextSegment:
    is_cdata: bool
    raw_start: int
    raw_end: int
```

普通文本段序列化时做 XML 实体转义；CDATA 段序列化时做 CDATA 结束符安全转义；CDATA段仅出现在CDATA起始标签的内容范围、以及普通结构标签内的原生CDATA块中，纯文本标签不产生CDATA段。


## 4. 建树主流程

总体流程：

1. Token 化，并建立 `opens_of` / `closes_of` 索引；
2. 单次扫描构造容错树；
3. 对隐式关闭节点做同名拆分；
4. 序列化为良构 XML；
5. `parse_xml` 最后交给 `lxml` / `xmltodict` 做语义解析。

伪代码：

```python
def fix_xml_with_text_tags(xml, text_tags=()):
    text_tags = set(text_tags)

    tokens = tokenize(xml)
    opens_of, closes_of = index_tokens(tokens)

    doc = Node("document")
    stack = [doc]
    pos = 0
    ti = 0

    while ti < len(tokens):
        kind, name, s, e = tokens[ti]

        # 追加 token 之前的原始文本
        if pos < s:
            if stack[-1].is_text_tag:
                consume_text_tag_raw(stack[-1], xml, pos, s)
            else:
                append_text(stack[-1], xml[pos:s])
            pos = s

        # 若当前处于 CDATA 内容模式，先按原始字符串推进
        # CDATA内容模式仅由两种场景触发：一是CDATA起始标签节点进入栈时自动设置，二是普通结构模式下遇到的原生合法CDATA段（当前栈顶为非text_tag的普通结构节点）
        if stack[-1].in_cdata:
            result = consume_cdata_content(stack, xml, tokens, ti, opens_of, closes_of)
            pos = result.new_pos
            ti = first_token_index_at_or_after(tokens, ti, pos)
            if result.closed_text_tag:
                stack.pop().auto_closed = result.auto_closed
            continue

        # 若栈顶是文本标签，判断当前 token 属于文本内容还是边界信号
        if stack[-1].is_text_tag:
            action = text_tag_token_action(
                stack, stack[-1], tokens, ti, opens_of, closes_of
            )
            if action == "text":
                append_raw_text(stack[-1], xml[s:e], kind)
                ti += 1
                pos = e
                continue
            else:  # "cut"
                stack.pop().auto_closed = True
                # 不消费当前 token，回到结构模式重新处理
                continue

        # 普通结构模式
        if kind == "end":
            handle_end_tag(stack, name, ti, opens_of, closes_of)
            ti += 1
            pos = e

        elif kind in ("comment", "self_close"):
            append_raw(stack[-1], xml[s:e])
            ti += 1
            pos = e

        else:  # start
            raw_start_tag = xml[s:e]
            # 解析并标准化修复标签属性
            parsed_name, fixed_attrs = parse_and_fix_attributes(raw_start_tag)
            node = Node(name=parsed_name, start_tag=raw_start_tag, attrs=fixed_attrs)
            stack[-1].children.append(node)
            node.parent = stack[-1]

            cdata_match = match_cdata_open(xml, e)

            if cdata_match.matched:
                # CDATA 起始标签：开始标签 + CDATA 前缀作为整体
                node.is_text_tag = True
                node.cdata_start = True
                node.cdata_open_prefix = cdata_match.raw_prefix
                node.content_pos = cdata_match.prefix_end
                node.in_cdata = True
            elif name in text_tags:
                # 普通纯文本标签
                node.is_text_tag = True
                node.cdata_start = False
                node.content_pos = e
                node.in_cdata = False

            stack.append(node)
            ti += 1
            pos = e

    # 收尾：隐式关闭栈中剩余节点
    while len(stack) > 1:
        stack.pop().auto_closed = True

    # 只拆分隐式关闭节点中的同名子节点
    split_auto_closed_same_name(doc)

    return serialize(doc)
```

关键点：

- 普通结构节点进入栈；
- 文本标签节点也进入栈，但其内容由专门规则处理；
- CDATA 起始标签强制进入文本标签模式，不再看 `name in text_tags`；
- 所有开始标签在节点创建时完成属性解析与标准化修复；
- 内容模式推进 `pos` 后，需要把 `ti` 同步到第一个 `start >= pos` 的 token。由于位置单调前进，可用指针循环跳过，总复杂度 O(n)。
- 若注释未找到 `-->`，注释到下一个 `<` 关闭。

## 5. 普通结构标签规则

### 5.1 标签属性通用解析与修复规则
所有开始标签（包括普通结构标签、纯文本标签、CDATA 起始标签）在完成 token 识别后，统一进行属性解析与标准化修复，保证输出属性语法良构，修复过程遵循以下规则：
1. **属性解析基础逻辑**：从原始开始标签字符串中提取标签名之后、标签结尾（`>` 或 `/>`）之前的内容作为属性扫描区域，逐段识别属性名与属性值的对应关系。
2. **未关闭属性引号处理**：如果扫描到的属性值使用单引号或双引号开头，但直到标签结束位置都未找到匹配的关闭引号，自动在标签结尾处补全匹配的关闭引号，将引号内所有剩余内容作为属性值。
3. **属性名标准化处理**：
   - 去除属性名前后误加的引号（如 `"id"="123"` 中的属性名 `id` 两侧引号）；
   - 移除属性名中不在 XML 允许范围内的特殊字符（如 `<`、`>`、`"`、`'`、`&`、空格等）；
   - 空属性名（经清洗后无有效字符）的属性直接丢弃。
4. **属性值标准化处理**：
   - 如果属性值未使用引号包裹，自动为其添加双引号包裹，将属性值到下一个空格或标签结尾之间的内容作为属性值；
   - 属性值内部的未转义特殊字符（`<`、`>`、`"`、`&`）自动转义为对应的XML实体，避免破坏XML结构。
5. **重复属性名处理**：如果同一开始标签中出现多个同名属性，只保留第一个属性值。
6. **结束标签属性处理**：所有结束标签（`</name>`）中出现的任何属性内容全部删除，只保留标签名与标准关闭结构，不做属性保留。

### 5.2 开始标签
普通开始标签：
- 创建 Node，关联修复后的标准化属性集合；
- 压栈；
- 若其名字在 `text_tags` 中，则进入纯文本标签模式；
- 若开始标签后紧跟兼容 CDATA 前缀，则进入 CDATA 起始标签模式，优先级高于 `text_tags` 判断。

### 5.3 关闭标签命中栈中同名节点

遇到 `</X>` 且栈中存在最近的 `X`：

- `X` 之上的所有未关闭节点全部标记 `auto_closed=True` 并弹出；
- `X` 本身由 `</X>` 正常关闭，标记 `explicit_close=True`。

示例：

```xml
<root><a>1<b>2</root>
```

在 `</root>` 处，`b`、`a` 被隐式关闭，`root` 显式关闭。

### 5.4 关闭标签未命中栈中节点

这是 LLM 常见错误关闭场景。采用“关闭前瞻”：

> 当前栈顶节点 `top` 未来是否还能在任意上级关闭之前，被自己的 `</top>` 正常关闭？

判断方式：

```python
def can_close_later(top, ti, opens_of, closes_of, stack):
    next_own = next_close_of(top.name, after=ti)
    next_ancestor = min(
        next_close_of(ancestor.name, after=ti)
        for ancestor in current_ancestors(stack)
    )
    return next_own is not None and (
        next_ancestor is None or next_own < next_ancestor
    )
```

处理规则：

- 如果 `top` 未来还能在上级关闭前正常关闭：  
  当前 `</X>` 大概率只是写错名字，**忽略它**，不提前关闭 `top`。
- 如果 `top` 已经不可能在上级关闭前正常关闭：  
  把 `top` 标记 `auto_closed=True` 并弹出，作为“这一层到此结束”的信号。
- 如果 `top` 就是根节点，保守忽略，避免整个文档被误伤。
- 未命中关闭标签处理时不消费当前 token；如果弹出后仍未命中，可继续处理同一个 `</X>`，直到命中、前瞻为真或到达根节点。

示例：

```xml
<root><result>aaa</answer><result>bbb</result></root>
```

- `</answer>` 未命中；
- 当前 `result` 后面还有 `</result>`，且早于 `</root>`；
- 因此不提前关闭外层 `result`，先忽略 `</answer>`；
- 后续形成同名嵌套；
- 外层 `result` 最终被 `</root>` 隐式关闭；
- 同名拆分后得到：

```xml
<root><result>aaa</result><result>bbb</result></root>
```

而：

```xml
<root><result>aaa</answer></root>
```

- `result` 后面没有自己的 `</result>`；
- `</answer>` 触发当前 `result` 隐式关闭；
- 输出：

```xml
<root><result>aaa</result></root>
```

### 5.5 同名开始标签与同名拆分

普通结构中遇到同名开始标签时，先按合法嵌套处理，压栈。  
不能在开始标签处直接拆分，因为：

```xml
<a><a>text</a></a>
```

是合法 XML。

最终只对 `auto_closed=True` 的节点做同名拆分：

> 如果隐式关闭节点内部出现同名子节点，则在该同名子节点处拆分，把该子节点及其后的兄弟提升出去。

伪代码：

```python
def split_auto_closed_same_name(node):
    for child in list(node.children):
        if isinstance(child, Node):
            split_auto_closed_same_name(child)

    if not node.auto_closed:
        return

    idx = first_index(
        node.children,
        lambda c: isinstance(c, Node) and c.name == node.name
    )
    if idx is None:
        return

    moved = node.children[idx:]
    node.children = node.children[:idx]

    parent = node.parent
    pos = parent.children.index(node)
    parent.children[pos + 1:pos + 1] = moved
    for m in moved:
        m.parent = parent
        if isinstance(m, Node):
            split_auto_closed_same_name(m)
```

效果：

```xml
<root><a>1<a>2</a></root>
```

建树后：

```text
root
  a(auto_closed=True)
    text "1"
    a(explicit_close=True)
      text "2"
```

拆分后：

```xml
<root><a>1</a><a>2</a></root>
```

合法嵌套：

```xml
<a><a>text</a></a>
```

外层 `a` 是显式关闭，不会参与拆分。

### 5.6 原生CDATA块保留规则

在普通结构模式下（即栈顶节点为非text_tag、非CDATA起始标签的普通结构节点），遇到原生合法CDATA段`<![CDATA[...]]>`时，保持原有结构不变：
- 完整识别CDATA起始与结束标志，将整个CDATA段作为普通结构内容保留到节点子节点中；
- 不拆分、不转义CDATA段内部内容、不修改CDATA前后缀；
- 该类CDATA段不关联任何text_tag的内容处理逻辑，不受text_tags名单影响。
- 如发生找不到 `]]>` 的情况，**直接寻找关闭标签**（按 5.3, 5.4），对最后一个未关闭的 CDATA 端，去除末尾疑似 `]]>`，并正确关闭该 CDATA 段。

### 5.7 根节点特殊处理

根节点的关闭标签必须从后往前找作为固定位置。若文档中间出现最外层根节点的结束：作为异常关闭标签，按异常关闭标签情况处理。

## 6. 普通 text_tag 内容模式

普通纯文本标签指名字在 `text_tags` 中、且开始标签后没有立即匹配 CDATA 前缀的标签。

### 6.1 token 处理规则

纯文本标签内容模式中遇到 token 时：

1. `</T>`：正常关闭当前 text_tag，标记 `explicit_close=True`。
2. `<T>`：同名开始标签。  
   根据强假设，text_tag 中真正的同名文本必须转义或放入 CDATA，因此这里直接判定当前 `T` 漏关闭：
   - 当前 text_tag 标记 `auto_closed=True` 并弹出；
   - 不消费当前 token；
   - 回到结构模式重新处理该 token。
3. 任意上级开始/结束标签 `<ancestor>` / `</ancestor>`：  
   同样视为当前 text_tag 漏关闭，隐式关闭当前 text_tag，不消费 token。
4. 外来标签 token，例如 `<other>`、`</other>`、注释、自闭合标签：  
   使用关闭前瞻判断：
   - 如果当前 text_tag 未来还能在自己的 `</T>` 关闭，且早于上级关闭：  
     该外来标签大概率只是 text_tag 内部未转义文本，**作为文本追加**，序列化时统一转义。
   - 如果当前 text_tag 已经不可能在上级关闭前正常关闭：  
     在它之前关闭当前 text_tag，当前 token 交给结构模式处理。

示例：

```xml
<root><file>abc<other>x</other></file></root>
```

在 `<other>` 处，后面存在 `</file>` 且早于 `</root>`，所以 `<other>x</other>` 作为 `file` 的文本内容，最终输出：

```xml
<root><file>abc&lt;other&gt;x&lt;/other&gt;</file></root>
```

而：

```xml
<root><file>abc<other>x</other></root>
```

在 `<other>` 处，后面不存在 `</file>`，当前 `file` 已无法正常关闭，因此在 `<other>` 前关闭 `file`，输出：

```xml
<root><file>abc</file><other>x</other></root>
```

### 6.2 内容处理规则

纯文本标签全程处于普通文本处理模式，严格遵循以下规则：
1. 所有内容统一使用普通XML实体转义规则，不采用CDATA段包裹；
2. 遇到的任何类似CDATA起始（如`<![CDATA[`、`<CDATA[`、`[CDATA[`等）或CDATA结束（如`]]>`、`]>`、`]] >`等）的字符串，全部作为普通文本内容处理，经过实体转义后输出，不识别为CDATA结构、不切换CDATA内容模式；
3. 不支持在纯文本标签内容中途嵌入CDATA段，不存在从普通文本模式切换到CDATA模式的逻辑。


## 7. CDATA 起始标签特殊处理

这是本设计需要重点保证的部分。

### 7.1 整体识别

当扫描到 start token 后，立即在开始标签结束位置匹配兼容 CDATA 起始前缀：

```python
cdata_match = match_cdata_open(xml, start_tag_end)
```

匹配成功时，将：

```text
<tag ...><![CDATA[
```

或兼容形式：

```text
<tag ...><CDATA[
<tag ...>[CDATA[
<tag ...>!CDATA[
...
```

作为一个整体。创建节点时：

```python
node.is_text_tag = True
node.cdata_start = True
node.cdata_open_prefix = matched_prefix
node.content_pos = prefix_end
node.in_cdata = True
```

重要规则：带 CDATA 起始的标签不再判断 `text_tags` 名单，直接适用 text_tags 的关闭与边界规则。

也就是说，只要开始标签后紧跟兼容 CDATA 前缀，即使 `name` 不在 `text_tags` 中，也按文本标签处理。

### 7.2 关闭查找优先级

CDATA 起始标签的关闭查找遵循严格的优先级顺序，优先级从高到低依次为：
1. 第一优先级（最高）：精确匹配组合关闭标志 `]]></name>`，即标准CDATA结束符紧跟当前标签的正常关闭标签，无任何中间字符或变体；
2. 第二优先级：匹配“疑似CDATA结束标志 + 当前标签正常关闭标签”的组合，兼容LLM常见的CDATA结束符书写错误（如`]></name>`、`]]> </name>`、`</CDATA></name>`等常见变体）；
3. 第三优先级：按照普通text_tag规则查找当前标签的正常关闭标签`</name>`，应用通用的关闭前瞻与隐式关闭规则；
4. 兜底规则：如果上述三级查找均未命中，则按text_tags规则使用边界信号提前关闭：
   - 上级开始/结束标签；
   - 同名开始标签；
   - 外来标签且关闭前瞻为假；
   - EOF。

上述优先级规则高于普通关闭标签处理规则。

### 7.3 组合关闭处理

如果从当前位置开始找到组合关闭 `]]></name>`：

- 内容截止到 `]]>` 起点；
- 组合关闭整体消费；
- 节点标记 `explicit_close=True`；
- 输出时统一输出标准形式：

```xml
<name attrs><![CDATA[内容]]></name>
```

其中内容通过 CDATA 安全转义函数处理，避免内部未转义 `]]>` 破坏结构。

### 7.4 普通关闭处理

如果组合关闭没有找到，但按 text_tags 规则找到了普通 `</name>`：

- 内容截止到 `</name>` 起点；
- 调用尾部清理函数，删除关闭标签前紧邻的正确或疑似 CDATA 结束符；
- 节点标记 `explicit_close=True`；
- 输出时补标准 CDATA 结束符和关闭标签：

```xml
<name attrs><![CDATA[清理后的内容]]></name>
```

需要删除/吸收的“正确或疑似写错的 `]]>`”由兼容 CDATA 结束识别正则判定为尾部残留的形式。正确或疑似 `]]>` 与关闭标签之间应支持零个或多个空白字符。

只删除尾部紧邻关闭标签的一个结束标记，避免误删真实内容。若真实内容确实需要这些字符，应转义或放入 CDATA。

### 7.5 提前关闭与 fallback

如果组合关闭和普通关闭都尚未出现，但遇到以下信号：

- 上级开始/结束标签；
- 同名开始标签；
- 外来标签 token 且关闭前瞻为假；
- EOF；

则在信号 token 之前截断 CDATA 内容，隐式关闭 CDATA 起始标签：

- 节点标记 `auto_closed=True`；
- 同样清理尾部疑似 `]]>`；
- 不消费触发信号 token；
- 回到结构模式处理该 token；
- 输出标准 CDATA 包裹和关闭标签。

示例：

```xml
<root><file><![CDATA[abc<other>x</other></root>
```

缺失 `]]>`。在 `<other>` 处：

- 后面没有 `</file>`；
- `file` 已无法正常关闭；
- 因此在 `<other>` 前截断 CDATA，关闭 `file`；
- `<other>` 作为结构节点继续处理。

输出：

```xml
<root><file><![CDATA[abc]]></file><other>x</other></root>
```

### 7.6 未转义 `]]>` 的兼容

CDATA 内容中出现未转义 `]]>` 时：

- 如果它后面紧跟 `</name>`，优先按组合关闭处理，`]]>` 作为关闭的一部分被消费，不进入内容；
- 如果它后面不是 `</name>`，不会被组合关闭误判；序列化时通过 CDATA 安全转义函数转为：
  ```text
  ]]]]><![CDATA[>
  ```
- 如果关闭标签前存在疑似写错的 `]]>` / `]>` / `]+>` 等，普通关闭时由尾部清理函数删除。

因此，CDATA 起始标签可以兼容以下情况：

```xml
<root><file><![CDATA[abc]]></file></root>
<root><file><![CDATA[abc]></file></root>
<root><file><![CDATA[abc</file></root>
<root><file><![CDATA[a]]>b</file></root>
```

并输出良构 XML。


## 8. 序列化规则

树构造完成后统一序列化，严格遵循以下规则：
- **开始标签生成逻辑**：根据节点名与已修复的标准化属性列表，拼接生成良构开始标签，属性格式为`key="value"`，相邻属性间用单个空格分隔，自闭合标签在结尾添加`/>`。
- **普通结构节点（非text_tag、非CDATA起始标签）**：  
  生成的良构开始标签 + 子内容 + `</name>`。即使 `auto_closed=True`，也补齐关闭标签。节点内部遇到的原生合法CDATA段保持原有结构不变，不做转义或修改。
- **纯文本标签节点（非CDATA起始的text_tag）**：  
  生成的良构开始标签 + 所有内容统一经普通XML实体转义后输出 + `</name>`。不使用CDATA段包裹内容，遇到的任何CDATA前后缀字符串都经过实体转义处理，不保留为CDATA结构。实体转义时只处理`<`、`>`、`&`字符，保留已有的合法XML实体不做二次转义。
- **CDATA 起始标签节点**：  
  生成的良构开始标签 + 标准`<![CDATA[`包裹全部内容 + 标准`]]>` + `</name>`。
  1. 内容中的裸`]]>`序列统一通过安全转义函数转换为`]]]]><![CDATA[>`，已处于合法转义格式的`]]]]><![CDATA[>`序列不做二次转义；
  2. 原始内容中、关闭标签前紧邻的正确或疑似写错的CDATA结束残留序列，在序列化前统一删除，不重复输出；
  3. 不保留原始文本中错误书写的CDATA前后缀，统一替换为标准CDATA结构。
- **结束标签**：仅由`</name>`构成，符合XML语法规范。
- **注释**：保留原始字符串不做修改。


## 9. `parse_xml` 流程

`parse_xml` 只做两层解析尝试，不在修复算法中途调用 XML parser：

1. 提取 `<root>...</root>`；
2. 快速路径：直接 `xmltodict.parse`。  
   如果成功，并且 `text_tags` 中没有出现意外嵌套子元素，直接返回。
3. 修复路径：调用一次 `fix_xml_with_text_tags`；
4. 修复结果交给 `lxml(recover=True)` 做最终语义校验/兜底；
5. 再交给 `xmltodict.parse` 返回字典。

伪代码：

```python
def parse_xml(s, root, text_tags=None, **kwargs):
    xml_str = find_xml_document(s, root, with_tag=True)
    if not xml_str:
        return None

    text_tags_set = set(text_tags or [])
    parse_kwargs = {
        "process_namespaces": False,
        "disable_entities": True,
    }
    parse_kwargs.update(kwargs)

    # 快速路径：正确 XML 不修复
    try:
        parsed = xmltodict.parse(xml_str, **parse_kwargs)
        if not (
            text_tags_set
            and parsed_dict_has_nested_text_tags(parsed, text_tags_set)
        ):
            return parsed
    except Exception:
        parsed = None

    # 单次修复
    fixed = fix_xml_with_text_tags(xml_str, text_tags_set)

    # parser 只在最后出现，负责语义校验/兜底
    try:
        root_elem = etree.fromstring(
            fixed,
            parser=etree.XMLParser(
                recover=True,
                resolve_entities=False,
                no_network=True,
            ),
        )
        fixed_xml = etree.tostring(root_elem, encoding="unicode")
        return xmltodict.parse(fixed_xml, **parse_kwargs)
    except Exception:
        return parsed
```


## 10. 复杂度

- Token 化：O(n)；
- 索引构建：O(n)；
- 属性解析与修复：O(n)；
- 主扫描：每个 token 最多被处理常数次，文本标签内容单调前进，总 O(n)；
- 关闭前瞻：  
  - 使用 `bisect` 在 `closes_of[name]` 中查下一个关闭标签，O(log n)；
  - 求最近上级关闭需要扫描当前栈，O(h)，h 为栈深；
  - 常见 LLM XML 栈深很小。若需要硬性上限，可对 h 设置阈值，超过后退化为保守策略。
- 同名拆分：每个节点最多被提升/处理常数次，O(n)；
- 序列化：O(n)；
- 修复过程不调用 XML parser；
- `parse_xml` 中 parser 只出现在快速路径和最终语义解析，最多常数次。

总体为 O(n log n) 或接近 O(n)，不进行多候选树搜索和打分。


## 11. 效果对照

| 输入 | 输出或行为 |
|---|---|
| `<root><result>aaa</answer><result>bbb</result></root>` | `<root><result>aaa</result><result>bbb</result></root>` |
| `<root><result>aaa</answer></root>` | `<root><result>aaa</result></root>` |
| `<root><a><b><c></a>d</b></c>` | 错误关闭处结束当前层，后续文本/标签尽量成为更浅节点 |
| `<root><file><![CDATA[abc<other>x</other></root>` | `<root><file><![CDATA[abc]]></file><other>x</other></root>` |
| `<root><code><![CDATA[ok]]></root>` | `<root><code><![CDATA[ok]]></code></root>` |
| `<root><file><![CDATA[abc]></file></root>` | 删除疑似 `]>`，输出 `<root><file><![CDATA[abc]]></file></root>` |
| `<root><file><![CDATA[a]]>b</file></root>` | 未转义 `]]>` 在内容中转义为 `]]]]><![CDATA[>`，保持良构 |
| `<root><file><![CDATA[a]]]]><![CDATA[b</file></root>` | 保留已转义的CDATA序列，不做二次转义 |
| `<root><file>abc<![CDATA[def]]>ghi</file></root>`（file为纯text_tag，无CDATA起始） | 将`<![CDATA[`、`]]>`作为普通文本转义，输出`<root><file>abc&lt;![CDATA[def]]&gt;ghi</file></root>` |
| text_tag 内外来标签，但后面有正常 `</file>` | 保留为文本并转义 |
| 正确同名嵌套 `<a><a>x</a></a>` | 原样保留，不拆分 |
| 漏关闭同名嵌套 `<root><a>1<a>2</a></root>` | `<root><a>1</a><a>2</a></root>` |
| 正确 CDATA 起始标签 `<file><![CDATA[abc]]></file>` | 快速路径不修复；修复路径也输出相同结构 |
| `<root><item id="1" name="test></item></root>`（name属性引号未关闭） | 自动补全引号，输出 `<root><item id="1" name="test"></item></root>` |
| `<root><item "id"=123 name=test></item></root>`（属性名带引号、属性值未加引号） | 清洗属性名、补全属性值引号，输出 `<root><item id="123" name="test"></item></root>` |
| `<root><data value="a<b&c" id="1" id="2"></data></root>`（属性值含未转义字符、重复属性名） | 转义属性值特殊字符、删除重复属性，输出 `<root><data value="a&lt;b&amp;c" id="1"></data></root>` |
| `</root id="1" class="test">`（结束标签带多余属性） | 删除所有属性，输出 `</root>` |


## 12. 核心不变量

1. 输出 XML 中所有开始标签都有匹配关闭标签；
2. 正确 XML 的快速路径不进入修复；
3. 合法同名嵌套不会被拆分，只有 `auto_closed=True` 的外层节点才参与同名拆分；
4. text_tag 非 CDATA 内容中遇到未转义同名/上级标签，视为当前 text_tag 漏关闭；
5. text_tag 中真正作为文本的同名/上级标签必须转义或放入 CDATA；
6. CDATA 起始标签不判断 `text_tags` 名单，强制按文本标签规则处理；
7. 纯文本标签（非CDATA起始的text_tag）的所有内容统一走普通XML实体转义，不支持内容中途嵌入CDATA段；遇到的任何CDATA前后缀字符串都作为普通文本转义输出；
8. CDATA 起始标签关闭时严格遵循三级优先级：先精确匹配`]]></name>`，再匹配疑似`]]>`+`</name>`，最后按text_tags规则查找关闭标签；
9. CDATA 起始标签输出时统一使用标准CDATA段包裹内容，内容中裸`]]>`转义为`]]]]><![CDATA[>`，已合法转义的序列不二次转义；关闭时必须删除标签前紧邻的正确或疑似`]]>`残留；
10. 非text_tag、非CDATA起始的普通结构标签内部的原生合法CDATA段，保持原有结构不变，不做修改；
11. 修复阶段只做字符串与树操作，不调用 XML parser；
12. parser 只在 `parse_xml` 入口快速路径和出口语义解析出现；
13. 单次修复、单次建树，不引入多候选打分；
14. 所有输出开始标签的属性均经过标准化修复，不存在未关闭引号、非法属性名、未转义特殊字符的语法问题；
15. 同一开始标签内重复出现的同名属性，取第一个值；
16. 所有结束标签不携带任何属性，完全符合XML语法规范。


## 13. 测试建议

建议覆盖以下类别：

1. **正确 XML 不修复**：
   - 普通嵌套；
   - 同名合法嵌套；
   - 正确 CDATA；
   - text_tag 中已转义特殊字符。
2. **错误关闭标签**：
   - 错误名字；
   - 根节点前错误关闭；
   - 多个连续错误关闭；
   - 错误关闭后继续合法标签。
3. **缺失关闭标签**：
   - 普通标签缺失；
   - 同名嵌套缺失；
   - 多层缺失后出现合法兄弟。
4. **text_tag**：
   - 外特殊字符；
   - 外来标签前瞻为真/假；
   - 同名/上级标签触发漏关闭；
   - 内容中包含CDATA前后缀字符串。
5. **CDATA 起始标签**：
   - 标准 `<![CDATA[`；
   - 兼容前缀；
   - 组合关闭 `]]></tag>`；
   - 普通关闭前疑似 `]]>` / `]>` / `]+>`；
   - 缺失 `]]>` 后上级关闭；
   - 缺失 `]]>` 后出现后续合法结构；
   - 内容中出现未转义 `]]>`；
   - 内容中出现已转义的CDATA序列，无二次转义；
   - 名称不在 `text_tags` 中但仍按 CDATA 起始标签处理。
6. **原生CDATA保留**：
   - 非text_tag标签内部的合法CDATA段，保持结构不变。
7. **标签属性修复**：
   - 未关闭引号的属性值，自动补全匹配的关闭引号；
   - 属性名误加引号、含非法特殊字符，自动清洗为合法可识别的属性名；
   - 未加引号的属性值，自动补全双引号包裹；
   - 属性值内含未转义的特殊字符，自动转义为对应XML实体；
   - 重复出现的同名属性，取第一个值；
   - 结束标签携带多余属性，自动删除所有属性内容。
8. **随机测试不变量**：
   - 输出可被 XML parser 解析；
   - 所有标签闭合；
   - 正确 CDATA 起始标签不被破坏；
   - 修复后再修复结果稳定；
   - text_tag 非 CDATA 内容的原始文本经转义后可恢复。