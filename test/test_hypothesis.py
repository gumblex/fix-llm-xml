"""
Property-based (invariant) unit tests for the fix_llm_xml module.
Uses unittest and hypothesis to validate key invariants of the XML repair functions.
"""
import re
import unittest
from xml.sax import saxutils
import xml.etree.ElementTree as ET

from hypothesis import given, strategies as st, assume, settings
from lxml import etree

import fix_llm_xml

# -------------------------------
# Strategies
# -------------------------------

# Colon removed from tag_name to avoid undeclared-namespace issues with lxml;
# namespace-prefix handling is orthogonal to the invariants tested here.
st_tag_name = st.from_regex(r'[a-zA-Z_][a-zA-Z0-9_.-]*', fullmatch=True)
st_char_no_controls = st.characters(codec='utf-8', exclude_categories=('Cc',))
st_unquoted_attr_value = st.from_regex(r'[A-Za-z0-9_.:-]*', fullmatch=True)


@st.composite
def text_with_combos(draw, combos=(), mandatory_combos=(), max_size=200):
    """
    Generate text containing 0+ occurrences of each specified character combination.

    Unlike plain st.text(), this strategy ensures that specific substrings
    (like ']]>', '<![CDATA[', etc.) can appear in the output with controlled
    frequency, making it suitable for testing escape/CDATA handling.

    Args:
        combos: sequence of strings that may be inserted into the generated text.
                Each combo is independently inserted 0-3 times at random positions.
        mandatory_combos: sequence of strings that MUST appear at least once
                          in the generated text.
        max_size: max final text size
    """
    if not combos and not mandatory_combos:
        return draw(st.text(alphabet=st_char_no_controls, max_size=max_size))
    all_combos = list(set(combos) | set(mandatory_combos))
    extra_combos = draw(st.lists(st.sampled_from(all_combos), min_size=0, max_size=3))
    used_combos = list(set(list(mandatory_combos) + extra_combos))
    # randomise order so mandatory combos are not always at the front
    if len(used_combos) > 1:
        shuffle_order = draw(st.permutations(range(len(used_combos))))
        used_combos = [used_combos[i] for i in shuffle_order]
    remaining_length = max_size
    fragment_max_size = max_size // max(1, len(used_combos))
    result = []
    for combo in used_combos:
        if fragment_max_size > 0:
            frag = draw(st.text(alphabet=st_char_no_controls, max_size=fragment_max_size))
            result.append(frag)
        else:
            frag = ''
        result.append(combo)
        remaining_length -= len(frag) + len(combo)
        if fragment_max_size > remaining_length:
            fragment_max_size = remaining_length
    if fragment_max_size > 0:
        frag = draw(st.text(alphabet=st_char_no_controls, max_size=fragment_max_size))
        result.append(frag)
    return ''.join(result)


# Pre-defined combo sets for common testing scenarios
CDATA_COMBOS = (fix_llm_xml.CDATA_END, fix_llm_xml.CDATA_START, fix_llm_xml.ESCAPED_CDATA_END)
XML_SPECIAL_COMBOS = ('<', '>', '&')


@st.composite
def xml_with_text_tag(
    draw,
    *,
    include_cdata_combos=False,
    include_xml_specials=False,
    use_cdata=None,
    missing_close=None,
    extra_close=None,
    missing_root_close=None,
    malformed_cdata=None,
    content_include=(),
    content_exclude=(),
    exclude_tname_tags=False,
    exclude_root_tags=False,
    exclude_cdata_close_tname=False,
    max_content_size=200,
):
    """
    Generate an XML fragment containing a text tag with configurable damage.

    Keyword Args:
        include_cdata_combos: if True, content may include CDATA-related sequences
                              (`]]>`, `<![CDATA[`, `]]]]><![CDATA[>`)
        include_xml_specials: if True, content may include XML special characters
                              (<, >, &)
        use_cdata:            if bool, force CDATA / normal mode; None => random
        missing_close:        force presence/absence of </tname>; None => random
        extra_close:          force an extra </tname>; None => random (only when
                              missing_close is False)
        missing_root_close:   force absence of </root>; None => random (only when
                              missing_close is True)
        malformed_cdata:      force a non-standard CDATA prefix; None => random
                              (only when use_cdata is True)
        content_include:      mandatory substrings that MUST appear in the content
        content_exclude:      substrings that must NOT appear in the content
                              (enforced via assume)
        exclude_tname_tags:   if True, content will never contain </tname> or <tname
        exclude_root_tags:    if True, content will never contain </root> or <root
        exclude_cdata_close_tname: if True, content will never contain ]]></tname>
        max_content_size:     max length of the generated content text
    Returns a dict with keys:
        xml, root, tname, content, use_cdata, missing_close,
        missing_root_close, extra_close, malformed_cdata
    """
    root = draw(st_tag_name)
    tname = draw(st_tag_name)
    assume(root != tname)

    # Resolve boolean parameters (None -> random)
    if use_cdata is None:
        use_cdata = draw(st.booleans())
    if missing_close is None:
        missing_close = draw(st.booleans())
    if extra_close is None:
        extra_close = draw(st.booleans()) if not missing_close else False
    elif missing_close:
        extra_close = False
    if missing_root_close is None:
        missing_root_close = draw(st.booleans()) if missing_close else False
    elif not missing_close:
        missing_root_close = False
    if malformed_cdata is None:
        malformed_cdata = draw(st.booleans()) if use_cdata else False
    elif not use_cdata:
        malformed_cdata = False

    # Build combo lists for content generation
    combos = set()
    if include_cdata_combos:
        combos.update(CDATA_COMBOS)
    if include_xml_specials:
        combos.update(XML_SPECIAL_COMBOS)
    for item in content_exclude:
        combos.discard(item)

    content = draw(text_with_combos(
        tuple(combos),
        mandatory_combos=tuple(content_include),
        max_size=max_content_size,
    ))

    # Static exclusions
    for ex in content_exclude:
        assume(ex not in content)

    # Dynamic tag-related exclusions
    if exclude_tname_tags:
        assume(f"</{tname}>" not in content)
        assume(f"<{tname}" not in content)
    if exclude_root_tags:
        assume(f"<{root}" not in content)
        assume(f"</{root}>" not in content)
    if exclude_cdata_close_tname:
        assume(f"]]></{tname}>" not in content)

    # Build inner string
    if use_cdata:
        if malformed_cdata:
            cdata_prefix = draw(st.sampled_from(
                ['<CDATA[', '[CDATA[', '<![cdata[', '<!CDATA[']))
            inner = f"{cdata_prefix}{content}]]>"
        else:
            inner = f"<![CDATA[{content}]]>"
    else:
        assume(not fix_llm_xml.CDATA_PREFIX_RE.match(content))
        inner = content

    open_tag = f"<{root}><{tname}>"
    close_tname = f"</{tname}>"
    close_root = f"</{root}>"

    if missing_close:
        if missing_root_close:
            xml_str = f"{open_tag}{inner}"
        else:
            xml_str = f"{open_tag}{inner}{close_root}"
    elif extra_close:
        xml_str = f"{open_tag}{inner}{close_tname}{close_tname}{close_root}"
    else:
        xml_str = f"{open_tag}{inner}{close_tname}{close_root}"

    return {
        'xml': xml_str,
        'root': root,
        'tname': tname,
        'content': content,
        'use_cdata': use_cdata,
        'missing_close': missing_close,
        'missing_root_close': missing_root_close,
        'extra_close': extra_close,
        'malformed_cdata': malformed_cdata,
    }


@st.composite
def xml_with_cdata_tag(draw, close_style='combo', root=None, tname=None, content=None):
    """Generate an XML fragment where the text tag starts with a CDATA prefix
    and uses a specific closing style."""
    if root is None:
        root = draw(st_tag_name)
    if tname is None:
        tname = draw(st_tag_name)
    assume(root != tname)
    if content is None:
        content = draw(st.text(alphabet=st_char_no_controls, max_size=100))
    assume(']]>' not in content)
    assume(f'</{tname}>' not in content)
    assume(f'<{tname}' not in content)
    assume(f'<{root}' not in content)
    assume(f'</{root}>' not in content)

    if close_style == 'combo':
        inner = f"<![CDATA[{content}]]>"
        close = f"</{tname}>"
    elif close_style == 'residue':
        inner = f"<![CDATA[{content}]>"
        close = f"</{tname}>"
    elif close_style == 'residue_space':
        inner = f"<![CDATA[{content}]]> "
        close = f"</{tname}>"
    elif close_style == 'cdata_close':
        inner = f"<![CDATA[{content}</CDATA>"
        close = f"</{tname}>"
    elif close_style == 'plain':
        inner = f"<![CDATA[{content}"
        close = f"</{tname}>"
    else:
        raise ValueError(close_style)

    xml = f"<{root}><{tname}>{inner}{close}</{root}>"
    return {'xml': xml, 'root': root, 'tname': tname, 'content': content}


@st.composite
def xml_with_broken_attrs(draw):
    """Generate an XML fragment with malformed attributes."""
    root = draw(st_tag_name)
    tname = draw(st_tag_name)
    assume(root != tname)

    num_attrs = draw(st.integers(min_value=0, max_value=3))
    attr_strs = []
    expected_attrs = {}

    for i in range(num_attrs):
        kind = draw(st.sampled_from([
            'normal', 'unclosed_quote', 'quoted_name', 'unquoted_value',
            'special_chars', 'duplicate'
        ]))
        attr_name = draw(st_tag_name)
        attr_value = draw(st.text(alphabet=st_char_no_controls, max_size=10))
        assume(not any(c in attr_value for c in '<>&"'))

        if kind == 'normal':
            attr_strs.append(f'{attr_name}="{attr_value}"')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = attr_value
        elif kind == 'unclosed_quote':
            # Must be the last attribute
            num_attrs = i + 1
            attr_strs.append(f'{attr_name}="{attr_value}')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = attr_value
            break
        elif kind == 'quoted_name':
            attr_strs.append(f'"{attr_name}"="{attr_value}"')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = attr_value
        elif kind == 'unquoted_value':
            unquoted_value = draw(st_unquoted_attr_value)
            attr_strs.append(f'{attr_name}={unquoted_value}')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = unquoted_value
        elif kind == 'special_chars':
            special = draw(st.sampled_from(['<', '>', '&']))
            val = attr_value + special
            attr_strs.append(f'{attr_name}="{val}"')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = val
        elif kind == 'duplicate':
            val1 = attr_value
            val2 = draw(st.text(alphabet=st_char_no_controls, max_size=10))
            assume(val1 != val2)
            assume(not any(c in val1 + val2 for c in '<>&"'))
            attr_strs.append(f'{attr_name}="{val1}"')
            attr_strs.append(f'{attr_name}="{val2}"')
            if attr_name not in expected_attrs:
                expected_attrs[attr_name] = val1  # first wins

    attr_str = ' '.join(attr_strs)
    if attr_str:
        attr_str = ' ' + attr_str

    xml = f'<{root}><{tname}{attr_str}>text</{tname}></{root}>'
    return {'xml': xml, 'root': root, 'tname': tname, 'expected_attrs': expected_attrs}


@st.composite
def random_xml(draw):
    """Generate a well-formed XML fragment using lxml.
    May include nested elements with attributes, text,
    comments, and processing instructions.
    Occasionally returns an empty string to represent an empty fragment.
    """
    max_depth = draw(st.integers(min_value=0, max_value=5))

    def gen_elem(depth: int):
        tag = draw(st_tag_name)
        elem = etree.Element(tag)

        # ----------------- 属性 -----------------
        num_attrs = draw(st.integers(min_value=0, max_value=2))
        for _ in range(num_attrs):
            key = draw(st_tag_name)
            value = draw(st.text(alphabet=st_char_no_controls, max_size=10))
            elem.set(key, value)

        # ----------------- 元素文本 -----------------
        if draw(st.booleans()):
            text_str = draw(st.text(alphabet=st_char_no_controls, max_size=30))
            elem.text = text_str

        # ----------------- 子节点 -----------------
        if depth < max_depth:
            num_children = draw(st.integers(min_value=0, max_value=3))
            for _ in range(num_children):
                kind = draw(st.sampled_from(['element', 'comment', 'pi']))
                if kind == 'element':
                    child = gen_elem(depth + 1)
                else:
                    comment_text = draw(st.text(alphabet=st_char_no_controls, max_size=20))
                    # 确保没有连续的“--”，避免 XML 注释格式错误
                    comment_text = comment_text.replace('--', '- - ').rstrip('-')
                    child = etree.Comment(comment_text)
                elem.append(child)
                # 子节点之后的 tail 文本
                if draw(st.booleans()):
                    tail_text = draw(st.text(alphabet=st_char_no_controls, max_size=20))
                    child.tail = tail_text
        elif draw(st.booleans()):
            comment_text = draw(st.text(alphabet=st_char_no_controls, max_size=20))
            comment_text = comment_text.replace('--', '- - ').rstrip('-')
            child = etree.Comment(comment_text)
            elem.append(child)

        return elem

    root = gen_elem(0)
    xml_str = etree.tostring(root, encoding='unicode', method='xml',
                             xml_declaration=False)
    return xml_str


@st.composite
def xml_with_optional_nested_text_tag(draw, text_tags, nested=None, root=None):
    """
    Generate a well-formed XML document containing a text tag, optionally with nested child elements.
    Uses lxml.etree for XML construction to ensure well-formed output.
    """
    if not text_tags:
        raise ValueError("text_tags must not be empty")
    tname = draw(st.sampled_from(list(text_tags)))
    if root is None:
        root_tag = draw(st_tag_name)
        assume(root_tag != tname)
    else:
        root_tag = root
        assume(root_tag != tname)

    # Build the element tree using lxml.etree
    root_elem = etree.Element(root_tag)
    tname_elem = etree.SubElement(root_elem, tname)

    # Optional attributes on the text tag
    if draw(st.booleans()):
        attr_value = draw(st_tag_name)
        tname_elem.set('a', attr_value)

    # Determine if nested content should be included
    if nested is None:
        has_nested = draw(st.booleans())
    else:
        has_nested = nested

    if has_nested:
        # Optional leading text
        if draw(st.booleans()):
            text = draw(st.text(alphabet=st_char_no_controls, min_size=1, max_size=10))
            assume(f'<{tname}' not in text and f'</{tname}>' not in text
                   and f'<{root_tag}' not in text and f'</{root_tag}>' not in text)
            tname_elem.text = text
        # First child element
        child_tag = draw(st_tag_name)
        assume(child_tag != tname)
        assume(child_tag != root_tag)
        child_elem = etree.SubElement(tname_elem, child_tag)
        child_text = draw(st.text(alphabet=st_char_no_controls, min_size=1, max_size=10))
        assume(f'<{tname}' not in child_text and f'</{tname}>' not in child_text
               and f'<{root_tag}' not in child_text and f'</{root_tag}>' not in child_text)
        child_elem.text = child_text
        # Optional second child or trailing text
        if draw(st.booleans()):
            if draw(st.booleans()):
                child2_tag = draw(st_tag_name)
                assume(child2_tag != tname)
                assume(child2_tag != root_tag)
                child2_elem = etree.SubElement(tname_elem, child2_tag)
                child2_text = draw(st.text(alphabet=st_char_no_controls, min_size=1, max_size=10))
                assume(f'<{tname}' not in child2_text and f'</{tname}>' not in child2_text
                       and f'<{root_tag}' not in child2_text and f'</{root_tag}>' not in child2_text)
                child2_elem.text = child2_text
            else:
                tail_text = draw(st.text(alphabet=st_char_no_controls, min_size=1, max_size=10))
                assume(f'<{tname}' not in tail_text and f'</{tname}>' not in tail_text
                       and f'<{root_tag}' not in tail_text and f'</{root_tag}>' not in tail_text)
                child_elem.tail = tail_text
    else:
        text = draw(st.text(alphabet=st_char_no_controls, min_size=1, max_size=30))
        assume(f'<{tname}' not in text and f'</{tname}>' not in text
               and f'<{root_tag}' not in text and f'</{root_tag}>' not in text)
        tname_elem.text = text

    tname_str = etree.tostring(
        tname_elem, encoding='unicode', method='xml', xml_declaration=False)

    re_tname = re.compile('^<%s[^>]*>(.*)</%s>$' % (re.escape(tname), re.escape(tname)))
    inner_str = re_tname.match(tname_str).group(1)

    xml_str = etree.tostring(
        root_elem, encoding='unicode', method='xml', xml_declaration=False)

    return {
        'xml': xml_str,
        'root': root_tag,
        'tname': tname,
        'has_nested': has_nested,
        'text_tags': list(text_tags),
        'inner_str': inner_str,
    }


@st.composite
def unbalanced_tag_events(draw):
    """Generate a sequence of XML tags (possibly unbalanced) without text."""
    events = draw(st.lists(
        st.tuples(st.sampled_from(['start', 'end', 'self_close']), st_tag_name),
        max_size=20))
    parts = []
    for ev_type, name in events:
        if ev_type == 'start':
            parts.append(f'<{name}>')
        elif ev_type == 'end':
            parts.append(f'</{name}>')
        else:
            parts.append(f'<{name}/>')
    return ''.join(parts)


# -------------------------------
# Validation helpers (lxml-based)
# -------------------------------

_WRAP_TAG = '__w__'


def unescape_cdata(text: str) -> str:
    """Revert fix_llm_xml.ESCAPED_CDATA_END back to fix_llm_xml.CDATA_END."""
    return text.replace(fix_llm_xml.ESCAPED_CDATA_END, fix_llm_xml.CDATA_END)


_XML_PREDEFINED_ENTITIES = {'lt': '<', 'gt': '>', 'amp': '&', 'quot': '"', 'apos': "'"}


def xml_unescape(text: str) -> str:
    """Decode XML entities exactly like an XML parser would: the five
    predefined named entities plus numeric character references. Unknown
    named entities are left untouched (fix_llm_xml escapes their '&', so a
    parser hands them back verbatim). Never apply this to text that was
    already decoded by lxml — that would decode twice."""
    def _repl(match):
        body = match.group(1)
        if body[0] == '#':
            try:
                if body[1] in 'xX':
                    return chr(int(body[2:], 16))
                return chr(int(body[1:]))
            except (ValueError, OverflowError):
                return match.group(0)
        return _XML_PREDEFINED_ENTITIES.get(body, match.group(0))
    return re.sub(r'&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);', _repl, text)


def is_parseable_by_lxml(xml_str):
    """Check if the XML string is well-formed enough for lxml to parse.

    Tries direct parsing first; for fragments without a single root,
    wraps in a synthetic root element and retries.
    """
    try:
        etree.fromstring(xml_str)
        return True
    except etree.XMLSyntaxError:
        pass
    try:
        etree.fromstring(f'<{_WRAP_TAG}>{xml_str}</{_WRAP_TAG}>')
        return True
    except etree.XMLSyntaxError:
        # avoid invalid entity
        if '&' in xml_str:
            assume(False)
        return False


def parse_and_extract_text(fixed_xml, tname):
    """Parse *fixed_xml* with lxml and return the full text content of the first
    ``<tname>`` child of the root element, or ``None`` on failure.

    Uses `itertext()` to correctly concatenate all text segments, including
    those split by CDATA sections.
    """
    try:
        root = etree.fromstring(fixed_xml)
    except etree.XMLSyntaxError:
        # avoid invalid entity
        if '&' in fixed_xml:
            assume(False)
        return None
    elem = root.find(tname)
    if elem is None:
        return None
    return ''.join(elem.itertext()) or ''  # or '' to handle empty content gracefully


# -------------------------------
# Test Cases
# -------------------------------

class TestFixXmlFinalTagsStructure(unittest.TestCase):
    """Invariants for tag-structure repair (no text tags or structural focus)."""

    @given(unbalanced_tag_events())
    def test_output_parseable(self, xml_str):
        """After repair with no text_tags, output must be parseable by lxml."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml_str, text_tags=[])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")

    @given(random_xml())
    def test_idempotent_random(self, xml_str):
        """Applying repair twice must give the same result."""
        fixed1 = fix_llm_xml.fix_xml_with_text_tags(xml_str, text_tags=[])
        fixed2 = fix_llm_xml.fix_xml_with_text_tags(fixed1, text_tags=[])
        self.assertEqual(fixed1, fixed2,
                         f"Not idempotent:\nFirst: {fixed1}\nSecond: {fixed2}")

    @given(random_xml())
    def test_good_xml_unchanged(self, xml_str):
        """If the input is already tag-balanced (no text), it should not be modified."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml_str, text_tags=[])
        self.assertEqual(xml_str, fixed,
                         "Balanced fragment was unnecessarily modified")


class TestFixXmlFinalTagsTextTagStructure(unittest.TestCase):
    """Structural integrity invariants when text tags are involved."""

    @given(xml_with_text_tag())
    def test_output_parseable(self, case):
        """After repair, output must be parseable by lxml."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[case['tname']])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")

    @given(xml_with_text_tag(include_cdata_combos=True, include_xml_specials=True))
    def test_output_parseable_with_combos(self, case):
        """With CDATA/XML-special sequences in content, output must still be parseable."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[case['tname']])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")

    @given(xml_with_text_tag(include_xml_specials=True))
    def test_idempotent(self, case):
        """Applying repair twice must give the same result."""
        tname = case['tname']
        fixed1 = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        fixed2 = fix_llm_xml.fix_xml_with_text_tags(fixed1, text_tags=[tname])
        self.assertEqual(fixed1, fixed2,
                         f"Not idempotent:\nFirst: {fixed1}\nSecond: {fixed2}")


class TestFixXmlFinalTagsTextContent(unittest.TestCase):
    """Invariants for plain-text tag content preservation."""

    # ---- 1. Well-closed --------------------------------------------------

    @given(xml_with_text_tag(
        include_cdata_combos=True,
        include_xml_specials=True,
        missing_close=False,
        extra_close=False,
        exclude_tname_tags=True,
        exclude_root_tags=True,
        exclude_cdata_close_tname=True,
    ))
    @settings(max_examples=500)
    def test_content_preserved_well_closed(self, case):
        """When the text tag is well-closed, content must be exactly preserved
        after repair and lxml parsing."""
        tname = case['tname']
        content = case['content']
        xml = case['xml']

        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        extracted = parse_and_extract_text(fixed, tname)
        if extracted is None:
            self.fail(f"Failed to extract text from repaired XML\nFixed: {fixed!r}")

        if case['use_cdata']:
            test_extracted = unescape_cdata(extracted)
            test_content = unescape_cdata(content)
        else:
            test_extracted = extracted
            test_content = xml_unescape(content)

        self.assertEqual(test_extracted, test_content,
                         f"Content mismatch.\nOriginal XML: {xml!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_optional_nested_text_tag(text_tags=["code"]))
    def test_parse_xml_content_preservation(self, case):
        """For well‑formed XML with a text tag (nested or not), the full
        unescaped inner content must survive a parse_xml roundtrip."""
        result = fix_llm_xml.parse_xml(
            case["xml"], case["root"],
            text_tags=case["text_tags"],
            strip_whitespace=False,
        )
        self.assertIsNotNone(result, f"parse_xml returned None for\n{case['xml']}")
        extracted = fix_llm_xml.get_xml_tag_text(result[case["root"]][case["tname"]])
        # extracted 已经过 xmltodict 的一次解码；inner_str 是 XML 源串，
        # 只需对 inner_str 做一次 unescape 即可。
        test_extracted = extracted
        test_content = saxutils.unescape(case["inner_str"])
        self.assertEqual(
            test_extracted, test_content,
            f"Content mismatch\nXML: {case['xml']}\n"
            f"Extracted: {extracted!r}\nExpected: {case['inner_str']!r}"
            )

    @given(xml_with_optional_nested_text_tag(text_tags=["code"], nested=True))
    def test_parse_xml_nested_flattened(self, case):
        """When nested elements exist inside a text tag, the result must NOT
        contain nested dicts for that tag."""
        result = fix_llm_xml.parse_xml(
            case["xml"], case["root"],
            text_tags=case["text_tags"],
            strip_whitespace=False,
        )
        self.assertIsNotNone(result)
        tag_value = result[case["root"]][case["tname"]]
        # After repair, the text tag value should be a string or a dict with
        # only @attrs / #text, never a nested element key.
        if isinstance(tag_value, dict):
            for k in tag_value:
                self.assertTrue(k.startswith("@") or k == "#text",
                                f"Unexpected nested key '{k}' in {tag_value}")
        elif isinstance(tag_value, list):
            for item in tag_value:
                if isinstance(item, dict):
                    for k in item:
                        self.assertTrue(k.startswith("@") or k == "#text")

    # ---- 2. Missing-close ------------------------------------------------

    @given(xml_with_text_tag(
        include_cdata_combos=True,
        include_xml_specials=True,
        missing_close=True,
        exclude_root_tags=True,
    ))
    def test_content_not_lost_missing_close(self, case):
        """When the text tag is missing its close tag, the structure must still
        be valid, and the original content must be a prefix of the extracted text
        (extra text may appear due to closing-tag ambiguity)."""
        tname = case['tname']
        content = case['content']

        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])

        # Structural integrity
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")

        # Content not lost
        extracted = parse_and_extract_text(fixed, tname)
        if extracted is not None and content:
            if case['use_cdata']:
                test_extracted = unescape_cdata(extracted)
                test_content = unescape_cdata(content)
            else:
                test_extracted = extracted
                test_content = xml_unescape(content)
            self.assertTrue(test_content.startswith(test_extracted),
                            f"Extracted text is not a prefix of original content.\n"
                            f"Original: {content!r}\nExtracted: {extracted!r}\n"
                            f"Fixed: {fixed!r}")

    # ---- 3. ]]> as plain text in normal mode -----------------------------

    @given(xml_with_text_tag(
        include_cdata_combos=True,
        use_cdata=False,
        missing_close=False,
        extra_close=False,
        content_include=(fix_llm_xml.CDATA_END,),
        content_exclude=(fix_llm_xml.CDATA_START,),
        exclude_tname_tags=True,
        exclude_root_tags=True,
    ))
    @settings(max_examples=200)
    def test_cdata_end_as_text_in_normal_mode(self, case):
        """When ']]>' appears as text content in a normal (non-CDATA) text tag,
        it must be properly escaped and exactly recoverable after lxml parsing.
        In normal mode ']]>' is just regular character data, not a CDATA ending."""
        tname = case['tname']
        content = case['content']

        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        extracted = parse_and_extract_text(fixed, tname)
        if extracted is None:
            self.fail(f"Failed to extract text from repaired XML\nFixed: {fixed!r}")

        if case['use_cdata']:
            test_extracted = unescape_cdata(extracted)
            test_content = unescape_cdata(content)
        else:
            test_extracted = extracted
            test_content = xml_unescape(content)

        self.assertEqual(test_extracted, test_content,
                         f"Content with ']]>' not preserved.\nOriginal: {content!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_text_tag(missing_close=False, exclude_root_tags=True))
    def test_text_tag_content_preserved(self, case):
        """
        Whatever damage is present (except missing close), the raw content inside
        a known text tag must be recoverable after repair via lxml parsing.
        """
        tname = case['tname']
        content = case['content']
        xml = case['xml']

        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")
        extracted = parse_and_extract_text(fixed, tname)
        if extracted is None:
            self.fail("Failed to extract text-tag content from repaired XML")
        if case['use_cdata']:
            test_extracted = unescape_cdata(extracted)
            test_content = unescape_cdata(content)
        else:
            test_extracted = extracted
            test_content = xml_unescape(content)
        self.assertEqual(test_extracted, test_content,
                         f"Content mismatch.\nOriginal XML: {xml!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_text_tag(
        missing_close=True,
        missing_root_close=True,
        exclude_root_tags=True,
    ))
    @settings(max_examples=100)
    def test_text_tag_missing_close_structure(self, case):
        """When text tag and root tag are both missing their close tags, the
        repaired output must be parseable and must not lose original content."""
        tname = case['tname']
        content = case['content']

        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")
        extracted = parse_and_extract_text(fixed, tname)
        if extracted is None:
            self.fail("Failed to extract text from repaired XML")
        if content:
            if case['use_cdata']:
                test_extracted = unescape_cdata(extracted)
                test_content = unescape_cdata(content)
            else:
                test_extracted = extracted
                test_content = xml_unescape(content)
            self.assertTrue(test_content.startswith(test_extracted),
                            f"Extracted text is not a prefix of original content.\n"
                            f"Original: {content!r}\nExtracted: {extracted!r}\n"
                            f"Fixed: {fixed!r}")

    @given(xml_with_text_tag())
    @settings(max_examples=100)
    def test_text_tag_idempotent(self, case):
        """Repair should be idempotent even when plain-text tags are involved."""
        tname = case['tname']
        fixed1 = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        fixed2 = fix_llm_xml.fix_xml_with_text_tags(fixed1, text_tags=[tname])
        self.assertEqual(fixed1, fixed2,
                         f"Not idempotent:\nFirst: {fixed1}\nSecond: {fixed2}")


class TestCdataStartTag(unittest.TestCase):
    """Invariants for CDATA start tag handling (design §7)."""

    @given(xml_with_text_tag(use_cdata=True, missing_close=False, extra_close=False))
    def test_cdata_start_tag_content_preserved(self, case):
        """Content is preserved even if the tag name is not in text_tags."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        self.assertIsNotNone(extracted)
        test_extracted = unescape_cdata(extracted)
        test_content = unescape_cdata(case['content'])
        self.assertEqual(test_extracted, test_content)

    @given(xml_with_cdata_tag(close_style='combo'))
    def test_cdata_combo_close(self, case):
        """Standard `]]></name>` combo close works."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(case['content']))

    @given(xml_with_cdata_tag(close_style='residue'))
    def test_cdata_residue_close(self, case):
        """`]>` residue before close tag is stripped."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        expected = case['content']
        # content 以 ']' 结尾时，content + ']>' 会形成标准 ']]>'，
        # 此时 XML 表达的实际内容比生成器记录的 content 少一个 ']'。
        if expected.endswith(']'):
            expected = expected[:-1]
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(expected))

    @given(xml_with_cdata_tag(close_style='residue_space'))
    def test_cdata_residue_space_close(self, case):
        """`]]> ` residue before close tag is stripped."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(case['content']))

    @given(xml_with_cdata_tag(close_style='cdata_close'))
    def test_cdata_cdata_close(self, case):
        """`</CDATA>` residue before close tag is stripped."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(case['content']))

    @given(xml_with_cdata_tag(close_style='plain'))
    def test_cdata_plain_close(self, case):
        """Plain `</name>` without any CDATA end works and outputs standard CDATA."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        extracted = parse_and_extract_text(fixed, case['tname'])
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(case['content']))

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=50),
    )
    def test_cdata_fallback_auto_close(self, root, tname, content):
        """When no close tag is found but a foreign tag appears, the CDATA tag
        is auto-closed at the boundary."""
        assume(root != tname)
        assume(']]>' not in content)
        assume(f'</{tname}>' not in content)
        assume(f'<{tname}' not in content)
        assume(f'<{root}' not in content)
        assume(f'</{root}>' not in content)
        foreign = 'other'
        xml = f"<{root}><{tname}><![CDATA[{content}<{foreign}></{foreign}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        extracted = parse_and_extract_text(fixed, tname)
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(content))
        # foreign tag should be a sibling
        root_elem = etree.fromstring(fixed)
        self.assertIsNotNone(root_elem.find(foreign))

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=30),
        st.text(alphabet=st_char_no_controls, min_size=1, max_size=30),
    )
    def test_cdata_internal_cdata_end_escaped(self, root, tname, prefix, suffix):
        """An unescaped `]]>` inside CDATA (not immediately before `</name>`)
        is escaped in the output."""
        assume(root != tname)
        assume(']]>' not in prefix + suffix)
        assume(not suffix.startswith(f'</{tname}>'))
        content = prefix + ']]>' + suffix
        xml = f"<{root}><{tname}><![CDATA[{content}]]></{tname}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        self.assertTrue(is_parseable_by_lxml(fixed))
        extracted = parse_and_extract_text(fixed, tname)
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(content))
        self.assertIn(fix_llm_xml.ESCAPED_CDATA_END, fixed)

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=20),
        st.text(alphabet=st_char_no_controls, max_size=20),
    )
    def test_cdata_already_escaped_not_double_escaped(self, root, tname, prefix, suffix):
        """An already-escaped CDATA end (`]]]]><![CDATA[>`) is not double-escaped."""
        assume(root != tname)
        assume(']]>' not in prefix + suffix)
        assume(fix_llm_xml.ESCAPED_CDATA_END not in prefix + suffix)
        content = prefix + fix_llm_xml.ESCAPED_CDATA_END + suffix
        xml = f"<{root}><{tname}><![CDATA[{content}]]></{tname}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        extracted = parse_and_extract_text(fixed, tname)
        self.assertEqual(unescape_cdata(extracted), unescape_cdata(content))


class TestAttributeRepair(unittest.TestCase):
    """Invariants for attribute repair (design §5.1)."""

    @given(xml_with_broken_attrs())
    def test_attributes_standardized(self, case):
        """Malformed attributes are repaired to well-formed ones."""
        fixed = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[])
        self.assertTrue(is_parseable_by_lxml(fixed),
                        f"lxml cannot parse: {fixed!r}")
        root_elem = etree.fromstring(fixed)
        elem = root_elem.find(case['tname'])
        self.assertIsNotNone(elem)
        for name, value in case['expected_attrs'].items():
            self.assertEqual(elem.get(name), value,
                             f"Attribute {name} mismatch in {fixed!r}")

    @given(st_tag_name, st.text(alphabet=st_char_no_controls, max_size=20).filter(lambda s: '>' not in s))
    def test_end_tag_attrs_stripped(self, tag_name, attr_str):
        """Attributes on end tags are removed."""
        xml = f'<root><{tag_name}>text</{tag_name} {attr_str}></root>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        self.assertTrue(is_parseable_by_lxml(fixed))
        self.assertIn(f'</{tag_name}>', fixed)
        self.assertNotIn(f'</{tag_name} ', fixed)


class TestNativeCdata(unittest.TestCase):
    """Invariants for native CDATA preservation in non-text structural tags."""

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=50).filter(lambda s: ']]>' not in s),
    )
    def test_native_cdata_preserved(self, root, tname, cdata_content):
        """Well-formed native CDATA inside a structural tag is preserved as-is."""
        assume(root != tname)
        xml = f"<{root}><{tname}><![CDATA[{cdata_content}]]></{tname}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        self.assertIn(f"<![CDATA[{cdata_content}]]>", fixed)
        self.assertTrue(is_parseable_by_lxml(fixed))

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=50).filter(lambda s: ']]>' not in s),
    )
    def test_native_cdata_missing_end(self, root, tname, cdata_content):
        """Missing `]]>` is repaired by finding the close tag."""
        assume(root != tname)
        xml = f"<{root}><{tname}><![CDATA[{cdata_content}</{tname}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        self.assertTrue(is_parseable_by_lxml(fixed))
        root_elem = etree.fromstring(fixed)
        elem = root_elem.find(tname)
        self.assertIsNotNone(elem)
        self.assertEqual(elem.text, cdata_content)


class TestTextTagBoundaries(unittest.TestCase):
    """Invariants for same-name and ancestor tags inside text tags (design §6.1)."""

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=20),
        st.text(alphabet=st_char_no_controls, max_size=20),
        st.text(alphabet=st_char_no_controls, max_size=20),
    )
    def test_same_name_in_text_tag(self, root, tname, prefix, middle, suffix):
        """A same-name start tag inside a text tag triggers implicit close and split."""
        assume(root != tname)
        assume(f'<{tname}' not in prefix + middle + suffix)
        assume(f'</{tname}>' not in prefix + middle + suffix)
        assume(f'<{root}' not in prefix + middle + suffix)
        assume(f'</{root}>' not in prefix + middle + suffix)
        assume('<' not in prefix + middle + suffix)
        xml = f"<{root}><{tname}>{prefix}<{tname}>{middle}</{tname}>{suffix}</{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[tname])
        root_elem = etree.fromstring(fixed)
        children = root_elem.findall(tname)
        self.assertEqual(len(children), 2,
                         f"Expected 2 {tname} elements, got {len(children)} in {fixed!r}")
        self.assertEqual(children[0].text or '', xml_unescape(prefix))
        self.assertEqual(children[1].text or '', xml_unescape(middle))
        self.assertEqual(children[1].tail or '', xml_unescape(suffix))

    @given(
        st_tag_name,
        st_tag_name,
        st.text(alphabet=st_char_no_controls, max_size=20),
        st.text(alphabet=st_char_no_controls, max_size=20),
    )
    def test_ancestor_in_text_tag(self, root, tname, prefix, middle):
        """An ancestor start tag inside a text tag triggers implicit close."""
        assume(root != tname)
        assume('<' not in prefix and '<' not in middle)
        assume(f'<{tname}' not in prefix + middle)
        assume(f'</{tname}>' not in prefix + middle)
        assume(f'<{root}' not in prefix + middle)
        assume(f'</{root}>' not in prefix + middle)

        xml = f"<{root}><{tname}>{prefix}<{root}>{middle}</{root}></{root}>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[tname])

        root_elem = etree.fromstring(fixed)

        t_elem = root_elem.find(tname)
        self.assertIsNotNone(t_elem, f"No {tname} found in {fixed!r}")
        self.assertEqual(t_elem.text or '', xml_unescape(prefix))

        inner_root = root_elem.find(root)
        self.assertIsNotNone(inner_root, f"No inner {root} found in {fixed!r}")
        self.assertEqual(inner_root.text or '', xml_unescape(middle))


class TestEscapeCdataEnds(unittest.TestCase):
    """Invariants for fix_llm_xml._escape_cdata_ends."""

    @given(text_with_combos(combos=(fix_llm_xml.CDATA_END, fix_llm_xml.ESCAPED_CDATA_END)))
    @settings(max_examples=200)
    def test_no_bare_cdata_end(self, s):
        """Output must not contain a bare CDATA_END outside of ESCAPED_CDATA_END."""
        escaped = fix_llm_xml._escape_cdata_ends(s)
        temp = escaped.replace(fix_llm_xml.ESCAPED_CDATA_END, '')
        self.assertNotIn(
            fix_llm_xml.CDATA_END, temp,
                         f"Bare CDATA_END found in: {escaped!r}")

    @given(text_with_combos(combos=(fix_llm_xml.CDATA_END, fix_llm_xml.ESCAPED_CDATA_END)))
    @settings(max_examples=200)
    def test_idempotent(self, s):
        """Escaping twice should have no additional effect."""
        once = fix_llm_xml._escape_cdata_ends(s)
        twice = fix_llm_xml._escape_cdata_ends(once)
        self.assertEqual(once, twice)


class TestEscapeXmlText(unittest.TestCase):
    """Invariants for fix_llm_xml._escape_xml_text."""

    @given(text_with_combos(combos=('<', '>', '&', '&lt;', '&gt;', '&amp;')))
    def test_no_bare_angle_brackets(self, s):
        """Output must not contain unescaped '<' or '>'."""
        escaped = fix_llm_xml._escape_xml_entity(s)
        temp = escaped.replace('&lt;', '\0L').replace('&gt;', '\0G').replace('&amp;', '\0A')
        self.assertNotIn('<', temp)
        self.assertNotIn('>', temp)

    @given(text_with_combos(combos=('<', '>', '&', '&lt;', '&gt;', '&amp;')))
    def test_preserves_existing_entities(self, s):
        """Already present XML entities must not be double-escaped."""
        escaped = fix_llm_xml._escape_xml_entity(s)
        self.assertNotIn('&amp;lt;', escaped)
        self.assertNotIn('&amp;gt;', escaped)
        self.assertNotIn('&amp;amp;', escaped)

    @given(text_with_combos(combos=('<', '>', '&', '&lt;', '&gt;', '&amp;')))
    def test_idempotent(self, s):
        """Escaping twice should give the same result as once."""
        once = fix_llm_xml._escape_xml_entity(s)
        twice = fix_llm_xml._escape_xml_entity(once)
        self.assertEqual(once, twice)


class TestGetXmlTagContent(unittest.TestCase):
    """Invariants for fix_llm_xml.find_xml_document."""

    @given(st.text(), st_tag_name)
    def test_result_is_substring(self, s, root):
        """Any returned value must be a contiguous substring of the input."""
        result = fix_llm_xml.find_xml_document(s, root, with_tag=False)
        if result is not None:
            self.assertIn(result, s)
        result_with_tag = fix_llm_xml.find_xml_document(s, root, with_tag=True)
        if result_with_tag is not None:
            self.assertIn(result_with_tag, s)

    @given(st_tag_name, st.text(max_size=50))
    def test_simple_extraction(self, root, content):
        """For a simple non-nested tag, the correct content is extracted."""
        s = f"<{root}>{content}</{root}>"
        self.assertEqual(fix_llm_xml.find_xml_document(s, root, with_tag=False), content)
        self.assertEqual(fix_llm_xml.find_xml_document(s, root, with_tag=True), s)

    @given(st_tag_name, st.text(max_size=50))
    def test_nested_tags_outer_extraction(self, root, inner_content):
        """When tags are nested, the outermost content block is returned."""
        s = f"<{root}>outer <{root}>{inner_content}</{root}> tail</{root}>"
        expected = f"outer <{root}>{inner_content}</{root}> tail"
        self.assertEqual(fix_llm_xml.find_xml_document(s, root, with_tag=False), expected)


class TestParseXmlTag(unittest.TestCase):
    """Invariants for fix_llm_xml._parse_xml_tag."""

    @given(st.text(), st.integers(min_value=0, max_value=1000))
    def test_tag_substring(self, s, pos):
        """The returned full_tag must equal the slice [start_pos:end_pos]."""
        assume(pos < len(s))
        parsed = fix_llm_xml._parse_xml_tag(s, pos)
        if parsed is not None:
            tag_type, name, full_tag, start_pos, end_pos = parsed
            self.assertEqual(full_tag, s[start_pos:end_pos])
            self.assertLessEqual(end_pos, len(s))

    @given(st_tag_name)
    def test_parse_start_tag(self, name):
        parsed = fix_llm_xml._parse_xml_tag(f"<{name}>", 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'start')
        self.assertEqual(parsed[1], name)

    @given(st_tag_name)
    def test_parse_end_tag(self, name):
        parsed = fix_llm_xml._parse_xml_tag(f"</{name}>", 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'end')
        self.assertEqual(parsed[1], name)

    @given(st_tag_name)
    def test_parse_self_close_tag(self, name):
        parsed = fix_llm_xml._parse_xml_tag(f"<{name}/>", 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'self_close')
        self.assertEqual(parsed[1], name)

    def test_parse_comment(self):
        parsed = fix_llm_xml._parse_xml_tag("<!-- comment -->", 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'comment')

    @given(st.text())
    def test_invalid_returns_none(self, s):
        """If the string does not start with '<', it should return None."""
        if not s.startswith('<'):
            self.assertIsNone(fix_llm_xml._parse_xml_tag(s, 0))


class TestParseXml(unittest.TestCase):
    """Invariants for fix_llm_xml.parse_xml (higher level)."""

    @given(st_tag_name, st.text(alphabet=st_char_no_controls, max_size=100))
    def test_roundtrip_wellformed(self, root, content):
        """A well-formed, auto-escaped XML should round-trip through fix_llm_xml.parse_xml."""
        elem = ET.Element(root)
        child = ET.SubElement(elem, 'data')
        child.text = content
        xml_str = ET.tostring(elem, encoding='unicode')
        result = fix_llm_xml.parse_xml(xml_str, root, text_tags=['data'])
        self.assertIsNotNone(result)
        data_text = fix_llm_xml.get_xml_tag_text(result[root]['data'])
        self.assertEqual(data_text.strip(), content.strip())

    @given(data=st.data())
    def test_parse_broken_xml(self, data):
        """Even with structural damage, fix_llm_xml.parse_xml should not raise and ideally return a dict."""
        root = "root"
        tname = "code"
        content = data.draw(st.text(max_size=50))
        use_cdata = data.draw(st.booleans())
        missing_close = data.draw(st.booleans())
        if use_cdata:
            inner = f"<![CDATA[{content}]]>"
        else:
            inner = content
        if missing_close:
            xml_str = f"<{root}><{tname}>{inner}</{root}>"
        else:
            xml_str = f"<{root}><{tname}>{inner}</{tname}></{root}>"
        result = fix_llm_xml.parse_xml(xml_str, root, text_tags=[tname])
        if result is not None:
            self.assertIn(root, result)


class TestGetXmlTagText(unittest.TestCase):
    """Unit tests for fix_llm_xml.get_xml_tag_text value handling."""

    def test_none_returns_empty(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text(None), '')

    def test_string_returns_string(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text('hello'), 'hello')

    def test_dict_with_text(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text({'#text': 'value'}), 'value')

    def test_list_takes_first(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text(['first', 'second']), 'first')

    def test_empty_list_returns_empty(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text([]), '')

    def test_other_returns_empty(self):
        self.assertEqual(fix_llm_xml.get_xml_tag_text(123), '')


if __name__ == '__main__':
    unittest.main()
