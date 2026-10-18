import html
import pathlib
import unittest
import xml.etree.ElementTree as ET
import fix_llm_xml


def text_of(elem):
    return ''.join(elem.itertext())


def is_parseable_by_et(xml_str):
    try:
        ET.fromstring(xml_str)
        return True
    except Exception:
        return False


class TestFindXmlDocument(unittest.TestCase):
    """Test cases for find_xml_document function"""

    def test_simple_extraction(self):
        """Test normal extraction of root tag content"""
        text = "Preamble text<root>Core content</root>Trailing text"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertEqual("Core content", result)

    def test_incomplete_start_tag(self):
        """Test that None is returned when valid start tag is missing"""
        text = "No valid <roo>start tag</root>"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertIsNone(result)

    def test_incomplete_end_tag(self):
        """Test that content is extracted till end of text when closing tag is missing"""
        text = "Has start tag<root>but no end tag"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertEqual("but no end tag", result)

    def test_multiple_same_tags(self):
        """Test extraction range from first opening to last closing tag when multiple same tags exist"""
        text = "First<root>Content 1</root>Middle text<root>Content 2</root>Last"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertEqual("Content 1</root>Middle text<root>Content 2", result)

    def test_tag_with_special_characters(self):
        """Test extraction of tags with special characters in name"""
        text = "Prefix<my-root-tag attr='test'>Inner content</my-root-tag>Suffix"
        result = fix_llm_xml.find_xml_document(text, "my-root-tag")
        self.assertEqual("Inner content", result)

    def test_start_tag_with_attributes(self):
        """Test extraction of start tag with attributes (with_tag mode)"""
        text = "Preamble<user id='123' name='Alice' enabled='true'>User info</user>Trailing"
        result = fix_llm_xml.find_xml_document(text, "user", with_tag=True)
        self.assertEqual("<user id='123' name='Alice' enabled='true'>User info</user>", result)

    def test_no_target_tag(self):
        """Test that None is returned when target tag does not exist"""
        text = "Whole text only has <other>other tags</other>, no target tag"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertIsNone(result)

    def test_end_tag_before_start_tag(self):
        """Test handling of abnormal scenario where closing tag appears before opening tag"""
        text = "</root>Closing tag comes first<root>Opening tag comes later"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertEqual("Opening tag comes later", result)

    def test_empty_tag(self):
        """Test extraction of empty tag"""
        text = "aaaa<root></root>bbbb"
        self.assertEqual('', fix_llm_xml.find_xml_document(text, "root"))
        self.assertEqual('<root></root>', fix_llm_xml.find_xml_document(text, "root", with_tag=True))

    def test_nested_tags_inside_root(self):
        """Test extraction when root tag contains nested tags"""
        text = "Pre<root><child1>Child content 1</child1><child2>Child content 2</child2></root>Post"
        result = fix_llm_xml.find_xml_document(text, "root")
        self.assertEqual("<child1>Child content 1</child1><child2>Child content 2</child2>", result)

    def test_tag_with_whitespace_in_attributes(self):
        """Test extraction of tags with whitespace in attribute values"""
        text = "Preamble<item class='product featured' price='99.99'>Product</item>Trailing"
        result = fix_llm_xml.find_xml_document(text, "item", with_tag=True)
        self.assertEqual("<item class='product featured' price='99.99'>Product</item>", result)

    def test_cdata_tag(self):
        """Test content extraction in CDATA mode"""
        text = "Preamble<file><![CDATA[File content]]></file>Trailing"
        result = fix_llm_xml.find_xml_document(text, "file", cdata=True)
        self.assertEqual("File content", result)
        text = "Preamble<file><![CDATA[<file><![CDATA[File content]]></file>]]></file>Trailing"
        result = fix_llm_xml.find_xml_document(text, "file", cdata=True)
        self.assertEqual("<file><![CDATA[File content]]></file>", result)
        text = "Preamble<file><![CDATA[File content"
        result = fix_llm_xml.find_xml_document(text, "file", cdata=True)
        self.assertEqual("File content", result)
        text = "File content"
        result = fix_llm_xml.find_xml_document(text, "file", cdata=True)
        self.assertIsNone(result)


class TestParseXML(unittest.TestCase):
    """Test cases for parse_xml function"""

    def test_simple_xml_with_attributes(self):
        """Test parsing of simple XML structure with attributes"""
        test_xml = """
        Some preamble text
        <root attr1="value1" attr2="value2">
            <child1>Text 1</child1>
            <child2>Text 2</child2>
        </root>
        Some trailing text
        """
        result = fix_llm_xml.parse_xml(test_xml, "root")
        self.assertIsNotNone(result)
        self.assertIn("root", result)
        self.assertEqual("value1", result["root"]["@attr1"])
        self.assertEqual("value2", result["root"]["@attr2"])
        self.assertEqual("Text 1", result["root"]["child1"])
        self.assertEqual("Text 2", result["root"]["child2"])

    def test_nested_xml_structure(self):
        """Test parsing of nested XML structure"""
        test_xml = """
        <response>
            <data>
                <item id="1">First item</item>
                <item id="2">Second item</item>
            </data>
            <status>success</status>
        </response>
        """
        result = fix_llm_xml.parse_xml(test_xml, "response")
        self.assertIsNotNone(result)
        self.assertIn("response", result)
        self.assertIn("data", result["response"])
        self.assertEqual("success", result["response"]["status"])
        items = result["response"]["data"]["item"]
        self.assertEqual(2, len(items))
        self.assertEqual("1", items[0]["@id"])
        self.assertEqual("First item", items[0]["#text"])

    def test_xml_with_namespace(self):
        """Test parsing of XML with namespaces"""
        test_xml = """
        <root xmlns:ns="http://example.com">
            <child>Normal child element</child>
            <ns:child>Namespaced child element</ns:child>
        </root>
        """
        result = fix_llm_xml.parse_xml(test_xml, "root")
        self.assertIsNotNone(result)
        self.assertIn("ns:child", result["root"])
        self.assertEqual("Namespaced child element", result["root"]["ns:child"])

    def test_invalid_xml(self):
        """Test fault-tolerant parsing of incomplete XML"""
        test_xml = """
        This is not a complete XML
        <root>
            <child>No closing tag
        """
        result = fix_llm_xml.parse_xml(test_xml, "root")
        self.assertEqual({'root': {'child': 'No closing tag'}}, result)

    def test_xml_with_comments(self):
        """Test parsing of XML with comments"""
        test_xml = """
        Preamble text
        <root>
            <!-- This is a comment -->
            <child>Content</child>
            <another>More content</another>
        </root>
        Trailing text
        """
        result = fix_llm_xml.parse_xml(test_xml, "root")
        self.assertIsNotNone(result)
        self.assertEqual("Content", result["root"]["child"])
        self.assertEqual("More content", result["root"]["another"])

    def test_xml_surrounded_by_text(self):
        """Test extraction and parsing of XML wrapped in unrelated text"""
        test_xml = """
        This is preamble text, can be very long
        Contains all kinds of characters!@#$%^&*()

        <data id="123">
            <name>Test Name</name>
            <value>100</value>
        </data>

        This is trailing text, may also contain special characters
        """
        result = fix_llm_xml.parse_xml(test_xml, "data")
        self.assertIsNotNone(result)
        self.assertEqual("123", result["data"]["@id"])
        self.assertEqual("Test Name", result["data"]["name"])
        self.assertEqual("100", result["data"]["value"])

    def test_empty_root_tag(self):
        """Test parsing of empty root tag"""
        test_xml = "<root></root>"
        result = fix_llm_xml.parse_xml(test_xml, "root")
        self.assertIsNotNone(result)
        self.assertIn("root", result)

    def test_multiple_root_tags(self):
        """Test that only the first matching root tag is extracted when multiple exist"""
        test_xml = """
        <root1>
            <child>First root</child>
        </root1>
        <root2>
            <child>Second root</child>
        </root2>
        """
        result = fix_llm_xml.parse_xml(test_xml, "root1")
        self.assertIsNotNone(result)
        self.assertEqual("First root", result["root1"]["child"])

    def test_force_list(self):
        """Test force_list parameter to force tags to be parsed as lists"""
        test_xml = """
        <root-tag special="true">
            <sub-tag>Content</sub-tag>
        </root-tag>
        """
        result = fix_llm_xml.parse_xml(test_xml, "root-tag", force_list=['sub-tag'])
        expected = {'root-tag': {
            '@special': 'true',
            'sub-tag': ['Content']
        }}
        self.assertEqual(expected, result)

    def test_nested_cdata(self):
        """Test parsing of nested CDATA sections"""
        test_xml = """
        begin
        <result>
        <file name="a.xml"><![CDATA[<result><![CDATA[inside1]]></result>]]></file>
        </result>
        end
        """
        result = fix_llm_xml.parse_xml(test_xml, 'result', force_list=['file'])
        expected = {'result': {'file': [
            {'@name': 'a.xml', '#text': '<result><![CDATA[inside1]]></result>'}
        ]}}
        self.assertEqual(expected, result)

    def test_very_complex_nested_cdata(self):
        """Test parsing integrity of extremely complex nested CDATA/code content"""
        this_file = pathlib.Path(__file__).read_text(encoding="utf-8")
        test_xml = """<root><file name="test.py"><![CDATA[%s]]></file></root>""" % (
            this_file.replace(']]>', ']]]]><![CDATA[>')
        )
        result = fix_llm_xml.parse_xml(
            test_xml, 'root',
            strip_whitespace=False,
            force_list=['file']
        )
        expected = {'root': {'file': [
            {'@name': 'test.py', '#text': this_file}
        ]}}
        self.assertEqual(expected, result)

    def test_well_formed_with_nested(self):
        xml_str = "<root><code><inner>hello</inner></code></root>"
        result = fix_llm_xml.parse_xml(xml_str, "root", text_tags=["code"], strip_whitespace=False)
        self.assertIsNotNone(result)
        text = fix_llm_xml.get_xml_tag_text(result["root"]["code"])
        # The nested element should have been flattened to escaped text
        self.assertEqual(html.unescape(text), "<inner>hello</inner>")

    def test_multiple_text_tags_partial_nested(self):
        xml_str = "<root><a>ok</a><b><c>1</c></b></root>"
        result = fix_llm_xml.parse_xml(xml_str, "root", text_tags=["a", "b"], strip_whitespace=False)
        self.assertIsNotNone(result)
        a_text = fix_llm_xml.get_xml_tag_text(result["root"]["a"])
        b_text = fix_llm_xml.get_xml_tag_text(result["root"]["b"])
        self.assertEqual(html.unescape(a_text), "ok")
        self.assertEqual(html.unescape(b_text), "<c>1</c>")

    def test_text_tag_with_attributes_and_nested(self):
        xml_str = '<root><code lang="py"><print>hello</print></code></root>'
        result = fix_llm_xml.parse_xml(xml_str, "root", text_tags=["code"], strip_whitespace=False)
        self.assertIsNotNone(result)
        code_val = result["root"]["code"]
        # Attributes should be preserved
        self.assertEqual(code_val.get("@lang"), "py")
        text = fix_llm_xml.get_xml_tag_text(code_val)
        self.assertEqual(html.unescape(text), "<print>hello</print>")

    def test_parse_xml_entity_not_double_decoded(self):
        """parse_xml must not decode XML entities twice."""
        xml = "<A><code>&amp;gt;</code></A>"
        result = fix_llm_xml.parse_xml(xml, "A", text_tags=["code"])
        self.assertIsNotNone(result)
        # 正确的语义：文本内容为字面量 "&gt;"（一次 decode 之后）
        self.assertEqual(
            fix_llm_xml.get_xml_tag_text(result["A"]["code"]),
            "&gt;",
        )


class TestGetXmlTagText(unittest.TestCase):
    """Test cases for get_xml_tag_text function"""

    def test_none_value_returns_empty(self):
        """None input returns empty string"""
        self.assertEqual(fix_llm_xml.get_xml_tag_text(None), "")

    def test_string_value_returned_as_is(self):
        """String input is returned directly"""
        self.assertEqual(fix_llm_xml.get_xml_tag_text("test content"), "test content")

    def test_list_takes_first_element(self):
        """List input takes first element and processes it"""
        self.assertEqual(fix_llm_xml.get_xml_tag_text(["first", "second"]), "first")
        self.assertEqual(fix_llm_xml.get_xml_tag_text([]), "")

    def test_dict_extracts_text_key(self):
        """Dict input extracts value from #text key"""
        self.assertEqual(fix_llm_xml.get_xml_tag_text({"#text": "text content", "@attr": "val"}), "text content")
        self.assertEqual(fix_llm_xml.get_xml_tag_text({"@attr": "val"}), "")

    def test_other_types_return_empty(self):
        """Non-supported types return empty string"""
        self.assertEqual(fix_llm_xml.get_xml_tag_text(123), "")
        self.assertEqual(fix_llm_xml.get_xml_tag_text(True), "")
        self.assertEqual(fix_llm_xml.get_xml_tag_text({"key": "val"}), "")


class TestFixXmlBasicStructure(unittest.TestCase):
    """Basic structural repair behavior for fix_xml_with_text_tags."""

    def test_empty_xml(self):
        """Empty string input returns empty string"""
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags("", []), "")

    def test_valid_xml_no_text_tags(self):
        """Valid XML without plain text tags is returned as-is"""
        xml = "<root><item>text</item></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), xml)

    def test_auto_close_unclosed_tag(self):
        """Unclosed normal tags are automatically completed"""
        xml = "<root><child>text"
        expected = "<root><child>text</child></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_multiple_unclosed_nested(self):
        """Multiple layers of unclosed tags are completed in reverse stack order"""
        xml = "<a><b><c>text</c></b>"
        expected = "<a><b><c>text</c></b></a>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_extra_closing_tag_as_text(self):
        """Extra mismatched closing tags are text"""
        xml = "<root><child>text</child></child></root>"
        expected = "<root><child>text</child>&lt;/child&gt;</root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)


class TestFixXmlRootCloseProtection(unittest.TestCase):
    """The outermost root must only be closed by its last closing tag."""

    def test_multiple_roots(self):
        """A non-final </root> must not close the root node early."""
        xml = "<root><a>first</a></root><root><b>second</b></root>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, [])
        expected = "<root><a>first</a>&lt;/root&gt;<root><b>second</b></root></root>"
        self.assertEqual(fixed, expected)

    def test_root_end_tag_inside_open_child_does_not_close_root(self):
        """A middle </root> cannot close the root while a child is still open."""
        xml = "<root><a>first</root><b>second</b></root>"
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, [])

        self.assertTrue(fixed.endswith("</root>"))
        self.assertEqual(fixed.count("<root>"), 1)
        self.assertEqual(fixed.count("</root>"), 1)

        root = ET.fromstring(fixed)
        self.assertEqual(text_of(root.find("a")), "first")
        self.assertEqual(text_of(root.find("b")), "second")

    def test_parse_xml_keeps_middle_root_close_inside_root(self):
        """parse_xml should keep content after a middle </root> inside the root."""
        xml = "preamble<root><a>first</a></root><b>second</b></root>trailing"
        result = fix_llm_xml.parse_xml(xml, "root")

        self.assertIsNotNone(result)
        self.assertEqual(result["root"]["a"], "first")
        self.assertEqual(result["root"]["b"], "second")


class TestFixXmlAttributes(unittest.TestCase):
    """Attribute parsing, repair, and serialization behavior."""

    def test_self_closing_tag_attributes_standardized(self):
        """Self-closing tags are preserved and attributes standardized to double quotes"""
        xml = "<root><child attr='val'/></root>"
        expected = '<root><child attr="val"/></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_tag_with_attributes_preserved(self):
        """Tag attributes are preserved as-is"""
        xml = '<root><a attr="val">text</a></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), xml)

    def test_attribute_with_special_chars_escaped(self):
        """Special characters in attribute values are escaped"""
        xml = '<file path="a>b.txt" name="test<c>">file content</file>'
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ['file'])
        expected = '<file path="a&gt;b.txt" name="test&lt;c&gt;">file content</file>'
        self.assertEqual(expected, result)

    def test_attribute_unclosed_quote_completed(self):
        """Unclosed attribute quote is completed at the tag end"""
        xml = '<root><item id="1" name="test></item></root>'
        expected = '<root><item id="1" name="test"></item></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_attribute_unquoted_value_and_quoted_name(self):
        """Attribute names are cleaned and unquoted values are quoted"""
        xml = '<root><item "id"=123 name=test></item></root>'
        expected = '<root><item id="123" name="test"></item></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_attribute_duplicate_first_wins_and_escaped(self):
        """Duplicate attributes keep the first, and special chars are escaped"""
        xml = '<root><data value="a<b&c" id="1" id="2"></data></root>'
        expected = '<root><data value="a&lt;b&amp;c" id="1"></data></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_attribute_name_illegal_chars_not_start(self):
        """Illegal characters in attribute names are removed"""
        xml = '<root><item a!b="c"></item></root>'
        expected = '<root>&lt;item a!b="c"&gt;&lt;/item&gt;</root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_attribute_value_valid_entity_preserved(self):
        """Valid entities in attribute values are not double-escaped"""
        xml = '<root><tag attr="a&quot;b"></tag></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), xml)

    def test_end_tag_attributes_removed(self):
        """Attributes on closing tags are removed"""
        xml = '<root></root id="1" class="test">'
        expected = '<root></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_unquoted_empty_value_before_next_attr(self):
        xml = '<A><B A= A="">text</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])

        root = ET.fromstring(fixed)
        b = root.find('B')
        self.assertIsNotNone(b)
        self.assertEqual(b.get('A'), '')

    def test_invalid_unicode_attr_name_cleaned(self):
        xml = '<A><B ²A="">text</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])

        root = ET.fromstring(fixed)
        b = root.find('B')
        self.assertIsNone(b)

    def test_attr_empty_value_then_quoted_name(self):
        """`A= "B"="x"` must parse as A="" and B="x"."""
        cases = [
            # (input, expected attrs on <B>)
            ('<A><B A= "A"="A:0">text</B></A>', {'A': ''}),
            ('<A><B A= "A"="">text</B></A>',    {'A': ''}),
            ('<A><B A= "B"="x">text</B></A>',   {'A': '', 'B': 'x'}),
        ]
        for xml, expected in cases:
            fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
            elem = ET.fromstring(fixed).find('B')
            self.assertIsNotNone(elem)
            for name, value in expected.items():
                self.assertEqual(
                    elem.get(name), value,
                    f"Expected {name}={value!r} in {fixed!r}",
                )

    def test_attr_invalid_qname_dropped(self):
        """Attribute names that are not valid QNames are dropped."""
        xml = '<A><B A:0="x" ok="y">text</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        elem = ET.fromstring(fixed).find('B')
        self.assertEqual(elem.get('ok'), 'y')
        self.assertIsNone(elem.get('A:0'))

    def test_attr_quoted_value_with_whitespace_still_preserved(self):
        """合法写法 `A = "foo"` 不应被误解析为空值。"""
        xml = '<A><B A = "foo">text</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        elem = ET.fromstring(fixed).find('B')
        self.assertEqual(elem.get('A'), 'foo')

    def test_attribute_value_ampersand_escaped(self):
        """Attribute values are escaped, not treated by text escaping"""
        xml = '<root><tag attr="a & b">text</tag></root>'
        expected = '<root><tag attr="a &amp; b">text</tag></root>'
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_parse_and_fix_attributes_cleans_illegal_name_chars(self):
        """属性名中的非法字符应被过滤，而不是要求开始标签扫描器接受它们。"""
        attrs = fix_llm_xml._parse_and_fix_attributes(
            ' A<="1" B&="2" C/="3" D\'="4"'
        )
        self.assertEqual(
            attrs,
            {
                'A': '1',
                'B': '2',
                'C': '3',
                'D': '4',
            },
        )


class TestFixXmlComments(unittest.TestCase):
    """Comment repair behavior."""

    def _assert_parseable(self, fixed):
        try:
            ET.fromstring(fixed)
        except Exception as exc:
            self.fail(f'cannot parse {fixed!r}: {exc}')

    def test_comment_preserved(self):
        """XML comments are preserved as-is"""
        xml = "<!-- comment --><root/>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), xml)

    def test_unterminated_comment_is_closed(self):
        fixed = fix_llm_xml.fix_xml_with_text_tags(
            '<root><!--unterminated</root>', []
        )
        self.assertEqual(fixed, '<root><!--unterminated--></root>')
        self._assert_parseable(fixed)

    def test_valid_comment_preserved(self):
        xml = '<root><!-- ok --></root>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, [])
        self.assertEqual(fixed, xml)
        self._assert_parseable(fixed)

    def test_comment_with_double_hyphen_sanitized(self):
        fixed = fix_llm_xml.fix_xml_with_text_tags(
            '<root><!--a--b</root>', []
        )
        self._assert_parseable(fixed)
        self.assertNotIn('--b', fixed)


class TestFixXmlPlainTextTags(unittest.TestCase):
    """Plain text tag behavior: content is escaped, not parsed as child structure."""

    def test_text_tag_plain_simple(self):
        """Simple text in normal mode is preserved as-is"""
        xml = "<root><code>hello</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_plain_escape(self):
        """< > & in normal mode are automatically escaped to &lt; &gt; &amp;"""
        xml = "<root><code>if a < b && c > d</code></root>"
        expected = "<root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_escape_without_entity(self):
        """Double escaping of existing valid entities is avoided in normal mode"""
        xml = "<root><code>if a < b &amp;&amp; c > d</code></root>"
        expected = "<root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_inner_tags_escaped(self):
        """Inner tags in normal mode are treated as text with angle brackets escaped"""
        xml = "<root><code><div>text</div></code></root>"
        expected = "<root><code>&lt;div&gt;text&lt;/div&gt;</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_unclosed_auto_close(self):
        """Unclosed tags in normal mode are auto-completed"""
        xml = "<root><code>text"
        expected = "<root><code>text</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_orphan_cdata_markers_escaped(self):
        """Orphan CDATA markers in normal mode are escaped as text"""
        result = fix_llm_xml.fix_xml_with_text_tags("<root><code>before <![CDATA[inner]]> after</code></root>", ["code"])
        self.assertIn("&lt;![CDATA[inner]]&gt;", result)

    def test_text_tag_ancestor_end_closes_text_tag(self):
        """Ancestor end tag inside a plain text tag closes the text tag"""
        xml = "<root><a><code>text</a></code></root>"
        expected = "<root><a><code>text</code></a>&lt;/code&gt;</root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_ancestor_start_closes_text_tag(self):
        """Ancestor start tag inside a plain text tag closes the text tag"""
        xml = "<root><a><code>text<a>x</a></code></root>"
        expected = "<root><a><code>text</code></a><a>x</a></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_self_closing_not_processed(self):
        """Self-closing plain text tags do not enter plain text processing mode"""
        xml = "<root><code/></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<code/>", result)


class TestFixXmlCdataStartTags(unittest.TestCase):
    """CDATA start tag behavior: start tag followed by a CDATA-like prefix."""

    def test_text_tag_cdata_simple(self):
        """Simple content in CDATA mode is preserved as-is"""
        xml = "<root><code><![CDATA[hello world]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_special_chars_unchanged(self):
        """Special characters like < > & in CDATA mode are not escaped"""
        xml = "<root><code><![CDATA[if a < b & c > d]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_special_chars_unchanged2(self):
        xml = "<A><B><![CDATA[]]]></B></A>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml), xml)

    def test_text_tag_cdata_nested_end_escaped(self):
        """Inner ]]> in CDATA mode are escaped to ESCAPED_CDATA_END sequence"""
        xml = "<root><code><![CDATA[text ]]> more text]]></code></root>"
        expected = "<root><code><![CDATA[text ]]]]><![CDATA[> more text]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_cdata_already_escaped_not_double_escaped(self):
        """Already escaped ESCAPED_CDATA_END sequences are not double-escaped"""
        xml = "<root><code><![CDATA[text ]]]]><![CDATA[> more]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_unclosed_auto_close(self):
        """Unclosed CDATA sections are auto-completed with ]]> and closing tag"""
        xml = "<root><code><![CDATA[text"
        expected = "<root><code><![CDATA[text]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_cdata_inner_full_cdata_escaped(self):
        """Inner ]]> of nested full CDATA blocks in CDATA mode are properly escaped"""
        xml = "<root><code><![CDATA[outer <![CDATA[inner]]> tail]]></code></root>"
        expected = "<root><code><![CDATA[outer <![CDATA[inner]]]]><![CDATA[> tail]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_nonstandard_cdata_prefix_recognized(self):
        """Non-standard CDATA-like prefixes are recognized and converted to standard CDATA"""
        xml = "<root><code><[CDATA[hello world]]></code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<![CDATA[hello world]]>", result)

    def test_malformed_cdata_prefix_normalized(self):
        """Malformed CDATA prefixes are normalized to standard format"""
        xml = "<text><<CDATA[some data with <inner> tag]]></text>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ['text'])
        expected = "<text><![CDATA[some data with <inner> tag]]></text>"
        self.assertEqual(expected, result)

    def test_compatibility_cdata_closing_recognized(self):
        """Compatibility CDATA closing markers (e.g. </CDATA></tag>) are recognized"""
        cases = (
            "<root><code><![CDATA[hello world</CDATA></code></root>",
            "<root><code><![CDATA[hello world]>></code></root>",
            "<root><code><![CDATA[hello world]></code></root>",
        )
        for xml in cases:
            result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
            expected = "<root><code><![CDATA[hello world]]></code></root>"
            self.assertEqual(expected, result)

    def test_cdata_fallback_plain_closing(self):
        """Fallback to </tag> closing when no ]]> is found in CDATA mode"""
        xml = "<root><code><![CDATA[text</code></root>"
        expected = "<root><code><![CDATA[text]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_cdata_start_tag_without_text_tags(self):
        """A tag with CDATA start is treated as text even if not in text_tags"""
        xml = "<root><x><![CDATA[a < b & c]]></x></root>"
        expected = "<root><x><![CDATA[a < b & c]]></x></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_cdata_start_tag_ancestor_fallback(self):
        """Missing CDATA end falls back to ancestor boundary and closes the tag"""
        xml = "<root><file><![CDATA[abc<other>x</other></root>"
        expected = "<root><file><![CDATA[abc]]></file><other>x</other></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)


class TestFixXmlNativeCdata(unittest.TestCase):
    """Native CDATA sections inside ordinary structural tags."""

    def test_native_cdata_in_structural_tag_preserved(self):
        """Native CDATA in a structural tag is preserved as-is"""
        xml = "<root><data><![CDATA[<x> & y]]></data></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), xml)

    def test_native_cdata_missing_end_before_close(self):
        """Missing native CDATA end is closed properly before its closing tag"""
        xml = "<root><data><![CDATA[abc</data></root>"
        expected = "<root><data><![CDATA[abc]]></data></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_invalid_tag_candidate_inside_missing_cdata_end(self):
        for content in ('<B', '<A', '<:'):
            xml = f'<A><B><![CDATA[{content}</B></A>'
            fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])

            root = ET.fromstring(fixed)
            b = root.find('B')
            self.assertIsNotNone(b, f'fixed={fixed!r}')
            self.assertEqual(text_of(b), content, f'fixed={fixed!r}')


class TestFixXmlSameNameTags(unittest.TestCase):
    """Same-name nested tag and text-tag splitting behavior."""

    def test_normal_mode_nested_same_name_splits(self):
        """Same-name start tag inside a plain text tag splits the text tag"""
        xml = "<root><code>outer <code>inner</code> tail</code></root>"
        expected = "<root><code>outer </code><code>inner</code> tail&lt;/code&gt;</root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_normal_mode_nested_same_name_escaped_literal_preserved(self):
        """Escaped same-name text inside a plain text tag is preserved"""
        xml = "<root><code>outer &lt;code&gt;inner&lt;/code&gt; tail</code></root>"
        expected = xml
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_cdata_mode_nested_same_name_preserved(self):
        """Nested same-name tags in CDATA mode are preserved as text"""
        xml = "<root><code><![CDATA[before <code>inner</code> after]]></code></root>"
        expected = "<root><code><![CDATA[before <code>inner</code> after]]></code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)


class TestFixXmlNamespaceTags(unittest.TestCase):
    """Namespace-qualified text tag behavior."""

    def test_namespace_text_tag_recognized(self):
        """Namespaced plain text tags are correctly recognized"""
        xml = "<root><ns:code>a < b</ns:code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["ns:code"])
        self.assertIn("&lt;", result)


class TestFixXmlMixedAndEscaping(unittest.TestCase):
    """Mixed normal/text tag behavior and automatic entity escaping."""

    def test_mixed_normal_and_text_tags(self):
        """Mixed normal and plain text tags are processed independently without interference"""
        xml = "<root><normal><code>text <div/></code></normal><code>hello</code></root>"
        expected = "<root><normal><code>text &lt;div/&gt;</code></normal><code>hello</code></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_multiple_different_text_tags(self):
        """Multiple different plain text tags are processed independently"""
        xml = "<root><code>a < b</code><pre>c > d</pre></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code", "pre"])
        self.assertIn("&lt;", result)
        self.assertIn("&gt;", result)

    def test_unicode_content_preserved(self):
        """Unicode/emoji content is fully preserved"""
        xml = "<root><code>こんにちは 🌍 中文测试</code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("こんにちは 🌍 中文测试", result)

    def test_normal_tag_text_escape_amp(self):
        """Ampersand in normal tag is escaped automatically"""
        xml = "<root><normal>a & b</normal></root>"
        expected = "<root><normal>a &amp; b</normal></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_text_escape_gt(self):
        """Greater-than in normal tag is escaped to &gt;"""
        xml = "<root><normal>a > b</normal></root>"
        expected = "<root><normal>a &gt; b</normal></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_text_preserve_entity(self):
        """Valid entities are not double-escaped in normal tags"""
        xml = "<root><normal>&amp; &lt; &gt;</normal></root>"
        expected = "<root><normal>&amp; &lt; &gt;</normal></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_mixed_content_escape(self):
        """Text around child tags is escaped while child tags remain"""
        xml = "<root><normal>a & b <inner/> c > d</normal></root>"
        expected = "<root><normal>a &amp; b <inner/> c &gt; d</normal></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_multiple_text_blocks(self):
        """Multiple text blocks in a tag are all escaped"""
        xml = "<root><item>first & second <inner/> third > fourth &amp; fifth</item></root>"
        expected = "<root><item>first &amp; second <inner/> third &gt; fourth &amp; fifth</item></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_unclosed_with_special_chars(self):
        """Unclosed normal tag with special chars is escaped and closed automatically"""
        xml = "<root><item>a & b"
        expected = "<root><item>a &amp; b</item></root>"
        self.assertEqual(fix_llm_xml.fix_xml_with_text_tags(xml, []), expected)

    def test_output_parseable_after_auto_escape(self):
        """After auto-escaping, the result is valid XML parseable by ET"""
        xml = "<root><data>a & b < c > d</data></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, [])
        # Should not raise any parse error
        root = ET.fromstring(result)
        self.assertIsNotNone(root)

    def test_mixed_text_tags_and_normal_tags_escaping(self):
        """Text-tags use their dedicated processing, normal tags use auto-escape"""
        xml = "<root><code>if a < b</code><normal>c & d</normal></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<code>if a &lt; b</code>", result)
        self.assertIn("<normal>c &amp; d</normal>", result)


class TestFixXmlContentIntegrity(unittest.TestCase):
    """Round-trip and output validity checks for repaired content."""

    def test_normal_mode_content_roundtrip(self):
        """Escaped content in normal mode matches original after parsing"""
        xml = "<root><code>if x < 5 && y > 10</code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        root = ET.fromstring(result)
        self.assertEqual(root.find("code").text, "if x < 5 && y > 10")

    def test_cdata_mode_content_roundtrip(self):
        """Escaped content in CDATA mode matches original after parsing"""
        xml = "<root><code><![CDATA[content]]>inside]]></code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        root = ET.fromstring(result)
        self.assertEqual(root.find("code").text, "content]]>inside")

    def test_cdata_mode_cdata_inside_roundtrip(self):
        xml = "<A><B><![CDATA[<![CDATA[]]></B></A>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, [])
        root = ET.fromstring(result)
        self.assertEqual(root.find("B").text, "<![CDATA[")

    def test_output_parseable_by_standard_parser(self):
        """Fixed XML can be parsed by standard XML parser"""
        xml = "<root><a><b>text<code><![CDATA[a < b]]></code></root>"
        result = fix_llm_xml.fix_xml_with_text_tags(xml, ["code"])
        # No parsing exception indicates pass
        ET.fromstring(result)

    def test_very_complex_nested_cdata_valid(self):
        """Test repair integrity of extremely complex nested CDATA/code content"""
        this_file = pathlib.Path(__file__).read_text(encoding="utf-8")
        test_xml = """<root><code name="test.py"><![CDATA[%s]]></code></root>""" % (
            this_file.replace(']]>', ']]]]><![CDATA[>')
        )
        result = fix_llm_xml.fix_xml_with_text_tags(test_xml)
        expected = """<root><code name="test.py"><![CDATA[%s]]></code></root>""" % (
            this_file.replace(']]>', ']]]]><![CDATA[>')
        )
        self.assertEqual(expected, result)

    def test_very_complex_nested_cdata_invalid(self):
        """Test repair integrity of extremely complex nested CDATA/code content"""
        self.maxDiff = None
        this_file = pathlib.Path(__file__).read_text(encoding="utf-8")
        test_xml = """<root><code name="test.py"><![CDATA[%s]]></code></root>""" % (
            this_file
        )
        result = fix_llm_xml.fix_xml_with_text_tags(test_xml)
        print(result)
        self.assertTrue(result.endswith("</root>"))


class TestTagCandidateValidation(unittest.TestCase):
    """Validation of raw tag candidates before they enter the tree."""

    def test_name_char_predicates(self):
        self.assertTrue(fix_llm_xml._is_xml_name_start_char('A'))
        self.assertTrue(fix_llm_xml._is_xml_name_start_char('_'))
        self.assertTrue(fix_llm_xml._is_xml_name_start_char(':'))
        self.assertFalse(fix_llm_xml._is_xml_name_start_char('1'))
        self.assertFalse(fix_llm_xml._is_xml_name_start_char('-'))

        self.assertTrue(fix_llm_xml._is_xml_name_char('1'))
        self.assertTrue(fix_llm_xml._is_xml_name_char('-'))
        self.assertTrue(fix_llm_xml._is_xml_name_char('.'))
        self.assertFalse(fix_llm_xml._is_xml_name_char('<'))
        self.assertFalse(fix_llm_xml._is_xml_name_char(' '))
        self.assertFalse(fix_llm_xml._is_xml_name_char('ab'))

    def test_reject_lt_outside_quote_in_start_tag(self):
        for candidate in (
            '<B a<="v">',
            '<a b=1<2>',
            '<B</B>',
            '<B </C>',
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNone(
                    fix_llm_xml._parse_xml_tag(candidate, 0),
                    f'{candidate!r} must not parse as a tag',
                )

    def test_invalid_candidate_in_text_tag_kept_as_text(self):
        xml = '<A><C>&<B </C></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['C'])

        root = ET.fromstring(fixed)
        c = root.find('C')
        self.assertIsNotNone(c)
        self.assertEqual(''.join(c.itertext()), '&<B ')

    def test_lt_in_quoted_attribute_value_still_parses(self):
        parsed = fix_llm_xml._parse_xml_tag('<a t="x<y">', 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'start')
        self.assertEqual(parsed[1], 'a')

    def test_start_tag_with_special_char_in_attr_name_rejected(self):
        """属性名区域出现 '<' 时，开始标签边界不明确，应拒绝该候选标签。"""
        self.assertIsNone(
            fix_llm_xml._parse_xml_tag('<item A<="1">', 0)
        )


class TestInvalidTagCandidateRegression(unittest.TestCase):
    """Regressions for invalid start tag candidates."""

    def test_invalid_char_after_tag_name_is_text(self):
        xml = '<A><B><B²</A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])

        root = ET.fromstring(fixed)
        b = root.find('B')
        self.assertIsNotNone(b)
        self.assertEqual(text_of(b), '<B²')

    def test_colon_only_is_text(self):
        xml = '<A><B><:</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])

        root = ET.fromstring(fixed)
        b = root.find('B')
        self.assertIsNotNone(b)
        self.assertEqual(text_of(b), '<:')

    def test_parse_xml_tag_rejects_invalid_delimiter(self):
        self.assertIsNone(fix_llm_xml._parse_xml_tag('<B²</A>', 0))
        self.assertIsNone(fix_llm_xml._parse_xml_tag('<:', 0))


class TestTextTagBoundaryRegression(unittest.TestCase):
    """Boundary regression for invalid candidates inside text tags."""

    def test_invalid_candidate_before_ancestor_in_text_tag(self):
        xml = '<A><C><B<A></A></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['C'])

        root = ET.fromstring(fixed)
        c = root.find('C')
        self.assertIsNotNone(c)
        self.assertEqual(text_of(c), '<B')

        inner_a = root.find('A')
        self.assertIsNotNone(inner_a)
        self.assertEqual(text_of(inner_a), '')


class TestInvalidTagDegradesToTextRegression(unittest.TestCase):
    """Deterministic regressions: an invalid tag candidate must degrade to
    plain text and must never be parsed as a start/end tag."""

    def _assert_parseable(self, fixed):
        try:
            ET.fromstring(fixed)
        except Exception as exc:
            self.fail(f'cannot parse {fixed!r}: {exc}')

    def _text_of(self, fixed, tag):
        root = ET.fromstring(fixed)
        elem = root.find(tag)
        self.assertIsNotNone(elem, f'no <{tag}> in {fixed!r}')
        return ''.join(elem.itertext())

    def test_lt_glued_to_name_degrades_to_text(self):
        # `<B</C>` used to parse as start tag `B`, swallowing the real `</C>`:
        # closes_of lost the token, the text tag was cut short, and a junk
        # `<B C="">` node was materialized.
        xml = '<A><C>0<![CDATA[<B</C></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['C'])
        self.assertEqual(self._text_of(fixed, 'C'), '0<![CDATA[<B')
        root = ET.fromstring(fixed)
        self.assertIsNone(root.find('B'), f'invalid tag became a node: {fixed!r}')

    def test_junk_char_glued_to_name_degrades_to_text(self):
        xml = '<A><B><B²</A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])
        self.assertEqual(self._text_of(fixed, 'B'), '<B²')

    def test_colon_candidate_degrades_to_text(self):
        xml = '<A><B><:</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])
        self.assertEqual(self._text_of(fixed, 'B'), '<:')

    def test_invalid_candidate_inside_missing_cdata_end(self):
        for content in ('<B', '<A', '<:'):
            with self.subTest(content=content):
                xml = f'<A><B><![CDATA[{content}</B></A>'
                fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
                self._assert_parseable(fixed)
                self.assertEqual(self._text_of(fixed, 'B'), content)
                root = ET.fromstring(fixed)
                self.assertEqual(len(root.findall('B')), 1,
                                 f'invalid tag became an extra node: {fixed!r}')

    def test_invalid_candidate_before_ancestor_in_text_tag(self):
        xml = '<A><C><B<A></A></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['C'])
        self.assertEqual(self._text_of(fixed, 'C'), '<B')
        root = ET.fromstring(fixed)
        self.assertIsNotNone(root.find('A'), f'fixed={fixed!r}')

    def test_parse_xml_tag_rejects_invalid_candidates(self):
        for candidate in ('<B²</A>', '<:</B>', '<B</B>', '<B<A>', '<a b=1<2>'):
            self.assertIsNone(fix_llm_xml._parse_xml_tag(candidate, 0),
                              f'{candidate!r} must not parse as a tag')
        self.assertIsNone(fix_llm_xml._parse_xml_tag('<:', 0))

    def test_lt_in_quoted_attribute_value_still_parses(self):
        # Guard against over-rejection: '<' inside quotes stays legal.
        parsed = fix_llm_xml._parse_xml_tag('<a t="x<y">', 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'start')
        self.assertEqual(parsed[1], 'a')

    def test_illegal_char_in_attribute_name_is_still_cleaned(self):
        xml = '<R><B a<="v">text</B></R>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
        self._assert_parseable(fixed)
        self.assertIsNone(ET.fromstring(fixed).find('B'))

    def test_unclosed_attr_quote_recovery_still_works(self):
        parsed = fix_llm_xml._parse_xml_tag('<item name="test></item>', 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'start')
        self.assertEqual(parsed[2], '<item name="test>')

    def test_trailing_brackets_are_legal_cdata_content(self):
        # A bare ']' / ']]' right before </B> is legal CDATA content; only
        # residues containing '>' may be stripped (design §7.6).
        for content in ('a]', 'a]]'):
            with self.subTest(content=content):
                xml = f'<A><B><![CDATA[{content}</B></A>'
                fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=[])
                self.assertEqual(self._text_of(fixed, 'B'), content)

    def test_predefined_and_numeric_entities_roundtrip_once(self):
        cases = {'&quot;': '"', '&apos;': "'", '&lt;': '<',
                 '&amp;lt;': '&lt;', '&#65;': 'A'}
        for raw, expected in cases.items():
            with self.subTest(entity=raw):
                xml = f'<A><B>{raw}</B></A>'
                fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])
                self.assertEqual(self._text_of(fixed, 'B'), expected)

    def test_unknown_named_entity_is_escaped(self):
        xml = '<A><B>&foo;</B></A>'
        fixed = fix_llm_xml.fix_xml_with_text_tags(xml, text_tags=['B'])
        self._assert_parseable(fixed)
        self.assertIn('&amp;foo;', fixed)
        self.assertEqual(self._text_of(fixed, 'B'), '&foo;')


class TestParsedDictHasNestedTextTags(unittest.TestCase):
    """Unit tests for _parsed_dict_has_nested_text_tags logic."""

    def test_empty_text_tags(self):
        parsed = {'root': {'code': {'child': 'value'}}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, set()))

    def test_text_tag_string_value(self):
        parsed = {'root': {'code': 'text'}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_empty(self):
        parsed = {'root': {'code': None}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_dict_with_only_attrs_and_text(self):
        parsed = {'root': {'code': {'@attr': '1', '#text': 'text'}}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_has_child_element(self):
        parsed = {'root': {'code': {'child': 'value'}}}
        self.assertTrue(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_list_with_child(self):
        parsed = {'root': {'code': [{'child': 'value'}]}}
        self.assertTrue(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_list_mixed_content(self):
        parsed = {'root': {'code': [{'#text': 'a'}, {'child': 'b'}]}}
        self.assertTrue(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_nested_text_tag_deep(self):
        parsed = {'root': {'wrapper': {'code': {'child': 'value'}}}}
        self.assertTrue(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_no_text_tag_in_parsed(self):
        parsed = {'root': {'other': {'child': 'value'}}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))

    def test_text_tag_with_namespace(self):
        parsed = {'root': {'ns:code': {'child': 'value'}}}
        self.assertTrue(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'ns:code'}))

    def test_text_tag_value_empty_list(self):
        parsed = {'root': {'code': []}}
        self.assertFalse(fix_llm_xml._parsed_dict_has_nested_text_tags(parsed, {'code'}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
