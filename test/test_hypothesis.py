"""
Property-based (invariant) unit tests for the fix_llm_xml module.
Uses unittest and hypothesis to validate key invariants of the XML repair functions.
"""
import html
import unittest
import xml.etree.ElementTree as ET

from hypothesis import given, strategies as st, assume, settings, reproduce_failure
from lxml import etree

import fix_llm_xml

# -------------------------------
# Strategies
# -------------------------------

# Colon removed from tag_name to avoid undeclared-namespace issues with lxml;
# namespace-prefix handling is orthogonal to the invariants tested here.
st_tag_name = st.from_regex(r'[a-zA-Z_][a-zA-Z0-9_.-]*', fullmatch=True)
st_char_no_controls = st.characters(codec='utf-8', exclude_categories=('Cc',))


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
def balanced_fragment(draw):
    leaf = st.just("") | st_tag_name.map(lambda n: f"<{n}/>")
    def kids_of(children):
        return st.builds(
            lambda tag, kids: f"<{tag}>" + "".join(kids) + f"</{tag}>",
            st_tag_name,
            st.lists(children, max_size=3),
        )
    return draw(st.recursive(leaf, kids_of, max_leaves=10))


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
        if '&' in fixed_xml:
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

    @given(unbalanced_tag_events())
    def test_idempotent(self, xml_str):
        """Applying repair twice must give the same result."""
        fixed1 = fix_llm_xml.fix_xml_with_text_tags(xml_str, text_tags=[])
        fixed2 = fix_llm_xml.fix_xml_with_text_tags(fixed1, text_tags=[])
        self.assertEqual(fixed1, fixed2,
                         f"Not idempotent:\nFirst: {fixed1}\nSecond: {fixed2}")

    @given(balanced_fragment())
    def test_balanced_input_unchanged(self, xml_str):
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
            test_extracted = html.unescape(extracted)
            test_content = html.unescape(content)

        self.assertEqual(test_extracted, test_content,
                         f"Content mismatch.\nOriginal XML: {xml!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    # ---- 2. Missing-close ------------------------------------------------

    @given(xml_with_text_tag(
        include_cdata_combos=True,
        include_xml_specials=True,
        missing_close=True,
    ))
    def test_content_not_lost_missing_close(self, case):
        """When the text tag is missing its close tag, the structure must still
        be valid, and the original content must appear as a substring of the
        extracted text (extra text may appear due to closing-tag ambiguity)."""
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
                test_extracted = html.unescape(extracted)
                test_content = html.unescape(content)
            self.assertIn(test_content, test_extracted,
                          f"Original content lost.\nOriginal XML: {case['xml']!r}\n"
                          f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    # ---- 3. ]]> as plain text in normal mode -----------------------------

    @given(xml_with_text_tag(
        include_cdata_combos=True,
        use_cdata=False,
        missing_close=False,
        extra_close=False,
        content_include=(fix_llm_xml.CDATA_END,),
        content_exclude=(fix_llm_xml.CDATA_START,),
        exclude_tname_tags=True,
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
            test_extracted = html.unescape(extracted)
            test_content = html.unescape(content)

        self.assertEqual(test_extracted, test_content,
                         f"Content with ']]>' not preserved.\nOriginal: {content!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_text_tag(missing_close=False))
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
            test_extracted = html.unescape(extracted)
            test_content = html.unescape(content)
        self.assertEqual(test_extracted, test_content,
                         f"Content mismatch.\nOriginal XML: {xml!r}\n"
                         f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_text_tag(missing_close=True, missing_root_close=True))
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
            self.assertIn(content, extracted,
                          f"Original content lost.\nOriginal: {content!r}\n"
                          f"Extracted: {extracted!r}\nFixed: {fixed!r}")

    @given(xml_with_text_tag())
    @settings(max_examples=100)
    def test_text_tag_idempotent(self, case):
        """Repair should be idempotent even when plain-text tags are involved."""
        tname = case['tname']
        fixed1 = fix_llm_xml.fix_xml_with_text_tags(case['xml'], text_tags=[tname])
        fixed2 = fix_llm_xml.fix_xml_with_text_tags(fixed1, text_tags=[tname])
        self.assertEqual(fixed1, fixed2,
                         f"Not idempotent:\nFirst: {fixed1}\nSecond: {fixed2}")


class TestEscapeCdataEnds(unittest.TestCase):
    """Invariants for fix_llm_xml._escape_cdata_ends."""

    @given(text_with_combos(combos=(fix_llm_xml.CDATA_END, fix_llm_xml.ESCAPED_CDATA_END)))
    @settings(max_examples=200)
    def test_no_bare_cdata_end(self, s):
        """Output must not contain a bare CDATA_END outside of ESCAPED_CDATA_END."""
        escaped = fix_llm_xml._escape_cdata_ends(s)
        temp = escaped.replace(fix_llm_xml.ESCAPED_CDATA_END, '')
        self.assertNotIn(fix_llm_xml.CDATA_END, temp,
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
