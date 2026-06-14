import pathlib
import unittest
import xml.etree.ElementTree as ET
from fix_llm_xml import parse_xml, find_xml_document, fix_xml_with_text_tags, get_xml_tag_text


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
        result = parse_xml(test_xml, "root")
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
        result = parse_xml(test_xml, "response")
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
        result = parse_xml(test_xml, "root")
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
        result = parse_xml(test_xml, "root")
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
        result = parse_xml(test_xml, "root")
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
        result = parse_xml(test_xml, "data")
        self.assertIsNotNone(result)
        self.assertEqual("123", result["data"]["@id"])
        self.assertEqual("Test Name", result["data"]["name"])
        self.assertEqual("100", result["data"]["value"])

    def test_empty_root_tag(self):
        """Test parsing of empty root tag"""
        test_xml = "<root></root>"
        result = parse_xml(test_xml, "root")
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
        result = parse_xml(test_xml, "root1")
        self.assertIsNotNone(result)
        self.assertEqual("First root", result["root1"]["child"])

    def test_force_list(self):
        """Test force_list parameter to force tags to be parsed as lists"""
        test_xml = """
        <root-tag special="true">
            <sub-tag>Content</sub-tag>
        </root-tag>
        """
        result = parse_xml(test_xml, "root-tag", force_list=['sub-tag'])
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
        result = parse_xml(test_xml, 'result', force_list=['file'])
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
        result = parse_xml(
            test_xml, 'root',
            strip_whitespace=False,
            force_list=['file']
        )
        expected = {'root': {'file': [
            {'@name': 'test.py', '#text': this_file}
        ]}}
        self.assertEqual(expected, result)


class TestGetXmlTagContent(unittest.TestCase):
    """Test cases for find_xml_document function"""

    def test_simple_extraction(self):
        """Test normal extraction of root tag content"""
        text = "Preamble text<root>Core content</root>Trailing text"
        result = find_xml_document(text, "root")
        self.assertEqual("Core content", result)

    def test_incomplete_start_tag(self):
        """Test that None is returned when valid start tag is missing"""
        text = "No valid <roo>start tag</root>"
        result = find_xml_document(text, "root")
        self.assertIsNone(result)

    def test_incomplete_end_tag(self):
        """Test that content is extracted till end of text when closing tag is missing"""
        text = "Has start tag<root>but no end tag"
        result = find_xml_document(text, "root")
        self.assertEqual("but no end tag", result)

    def test_multiple_same_tags(self):
        """Test extraction range from first opening to last closing tag when multiple same tags exist"""
        text = "First<root>Content 1</root>Middle text<root>Content 2</root>Last"
        result = find_xml_document(text, "root")
        self.assertEqual("Content 1</root>Middle text<root>Content 2", result)

    def test_tag_with_special_characters(self):
        """Test extraction of tags with special characters in name"""
        text = "Prefix<my-root-tag attr='test'>Inner content</my-root-tag>Suffix"
        result = find_xml_document(text, "my-root-tag")
        self.assertEqual("Inner content", result)

    def test_start_tag_with_attributes(self):
        """Test extraction of start tag with attributes (with_tag mode)"""
        text = "Preamble<user id='123' name='Alice' enabled='true'>User info</user>Trailing"
        result = find_xml_document(text, "user", with_tag=True)
        self.assertEqual("<user id='123' name='Alice' enabled='true'>User info</user>", result)

    def test_no_target_tag(self):
        """Test that None is returned when target tag does not exist"""
        text = "Whole text only has <other>other tags</other>, no target tag"
        result = find_xml_document(text, "root")
        self.assertIsNone(result)

    def test_end_tag_before_start_tag(self):
        """Test handling of abnormal scenario where closing tag appears before opening tag"""
        text = "</root>Closing tag comes first<root>Opening tag comes later"
        result = find_xml_document(text, "root")
        self.assertEqual("Opening tag comes later", result)

    def test_empty_tag(self):
        """Test extraction of empty tag"""
        text = "aaaa<root></root>bbbb"
        self.assertEqual('', find_xml_document(text, "root"))
        self.assertEqual('<root></root>', find_xml_document(text, "root", with_tag=True))

    def test_nested_tags_inside_root(self):
        """Test extraction when root tag contains nested tags"""
        text = "Pre<root><child1>Child content 1</child1><child2>Child content 2</child2></root>Post"
        result = find_xml_document(text, "root")
        self.assertEqual("<child1>Child content 1</child1><child2>Child content 2</child2>", result)

    def test_tag_with_whitespace_in_attributes(self):
        """Test extraction of tags with whitespace in attribute values"""
        text = "Preamble<item class='product featured' price='99.99'>Product</item>Trailing"
        result = find_xml_document(text, "item", with_tag=True)
        self.assertEqual("<item class='product featured' price='99.99'>Product</item>", result)

    def test_cdata_tag(self):
        """Test content extraction in CDATA mode"""
        text = "Preamble<file><![CDATA[File content]]></file>Trailing"
        result = find_xml_document(text, "file", cdata=True)
        self.assertEqual("File content", result)
        text = "Preamble<file><![CDATA[<file><![CDATA[File content]]></file>]]></file>Trailing"
        result = find_xml_document(text, "file", cdata=True)
        self.assertEqual("<file><![CDATA[File content]]></file>", result)
        text = "Preamble<file><![CDATA[File content"
        result = find_xml_document(text, "file", cdata=True)
        self.assertEqual("File content", result)
        text = "File content"
        result = find_xml_document(text, "file", cdata=True)
        self.assertIsNone(result)


class TestFixXmlFinalTags(unittest.TestCase):
    """Test cases for fix_xml_final_tags function"""

    # ------------------------------ Basic features: No plain text tags scenario ------------------------------
    def test_empty_xml(self):
        """Empty string input returns empty string"""
        self.assertEqual(fix_xml_with_text_tags("", []), "")

    def test_valid_xml_no_text_tags(self):
        """Valid XML without plain text tags is returned as-is"""
        xml = "<root><item>text</item></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), xml)

    def test_auto_close_unclosed_tag(self):
        """Unclosed normal tags are automatically completed"""
        xml = "<root><child>text"
        expected = "<root><child>text</child></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_multiple_unclosed_nested(self):
        """Multiple layers of unclosed tags are completed in reverse stack order"""
        xml = "<a><b><c>text</c></b>"
        expected = "<a><b><c>text</c></b></a>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_remove_extra_closing_tag(self):
        """Extra mismatched closing tags are discarded"""
        xml = "<root><child>text</child></child></root>"
        expected = "<root><child>text</child></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_self_closing_tag_preserved(self):
        """Self-closing tags are preserved as-is"""
        xml = "<root><child attr='val'/></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), xml)

    def test_comment_preserved(self):
        """XML comments are preserved as-is"""
        xml = "<!-- comment --><root/>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), xml)

    def test_tag_with_attributes_preserved(self):
        """Tag attributes are preserved as-is"""
        xml = '<root><a attr="val">text</a></root>'
        self.assertEqual(fix_xml_with_text_tags(xml, []), xml)

    def test_attribute_with_special_chars(self):
        """Special characters like < > inside attribute values are correctly preserved"""
        xml = '<file path="a>b.txt" name="test<c>">file content</file>'
        result = fix_xml_with_text_tags(xml, ['file'])
        expected = '<file path="a>b.txt" name="test<c>">file content</file>'
        self.assertEqual(expected, result)

    # ------------------------------ Plain text tags: Normal outer mode ------------------------------
    def test_text_tag_plain_simple(self):
        """Simple text in normal mode is preserved as-is"""
        xml = "<root><code>hello</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_plain_escape(self):
        """< > & in normal mode are automatically escaped to &lt; &gt; &amp;"""
        xml = "<root><code>if a < b && c > d</code></root>"
        expected = "<root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_escape_without_entity(self):
        """Double escaping of existing valid entities is avoided in normal mode"""
        xml = "<root><code>if a < b &amp;&amp; c > d</code></root>"
        expected = "<root><code>if a &lt; b &amp;&amp; c &gt; d</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_inner_tags_escaped(self):
        """Inner tags in normal mode are treated as text with angle brackets escaped"""
        xml = "<root><code><div>text</div></code></root>"
        expected = "<root><code>&lt;div&gt;text&lt;/div&gt;</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_unclosed_auto_close(self):
        """Unclosed tags in normal mode are auto-completed"""
        xml = "<root><code>text"
        expected = "<root><code>text</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_plain_orphan_cdata_markers_escaped(self):
        """Orphan CDATA markers in normal mode are escaped as text"""
        result = fix_xml_with_text_tags("<root><code>before <![CDATA[inner]]> after</code></root>", ["code"])
        self.assertIn("&lt;![CDATA[inner]]&gt;", result)

    # ------------------------------ Plain text tags: CDATA outer mode ------------------------------
    def test_text_tag_cdata_simple(self):
        """Simple content in CDATA mode is preserved as-is"""
        xml = "<root><code><![CDATA[hello world]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_special_chars_unchanged(self):
        """Special characters like < > & in CDATA mode are not escaped"""
        xml = "<root><code><![CDATA[if a < b & c > d]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_nested_end_escaped(self):
        """Inner ]]> in CDATA mode are escaped to ESCAPED_CDATA_END sequence"""
        xml = "<root><code><![CDATA[text ]]> more text]]></code></root>"
        expected = "<root><code><![CDATA[text ]]]]><![CDATA[> more text]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_cdata_already_escaped_not_double_escaped(self):
        """Already escaped ESCAPED_CDATA_END sequences are not double-escaped"""
        xml = "<root><code><![CDATA[text ]]]]><![CDATA[> more]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), xml)

    def test_text_tag_cdata_unclosed_auto_close(self):
        """Unclosed CDATA sections are auto-completed with ]]> and closing tag"""
        xml = "<root><code><![CDATA[text"
        expected = "<root><code><![CDATA[text]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_text_tag_cdata_inner_full_cdata_escaped(self):
        """Inner ]]> of nested full CDATA blocks in CDATA mode are properly escaped"""
        xml = "<root><code><![CDATA[outer <![CDATA[inner]]> tail]]></code></root>"
        expected = "<root><code><![CDATA[outer <![CDATA[inner]]]]><![CDATA[> tail]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    # ------------------------------ Compatibility CDATA prefix/suffix ------------------------------
    def test_nonstandard_cdata_prefix_recognized(self):
        """Non-standard CDATA-like prefixes are recognized and converted to standard CDATA"""
        xml = "<root><code><[CDATA[hello world]]></code></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<![CDATA[hello world]]>", result)

    def test_malformed_cdata_prefix_normalized(self):
        """Malformed CDATA prefixes are normalized to standard format"""
        xml = "<text><<CDATA[some data with <inner> tag]]></text>"
        result = fix_xml_with_text_tags(xml, ['text'])
        expected = "<text><![CDATA[some data with <inner> tag]]></text>"
        self.assertEqual(expected, result)

    def test_compatibility_cdata_closing_recognized(self):
        """Compatibility CDATA closing markers (e.g. </CDATA></tag>) are recognized"""
        cases = (
            "<root><code><![CDATA[hello world</CDATA></code></root>",
            "<root><code><![CDATA[hello world]]]]></code></root>",
            "<root><code><![CDATA[hello world]></code></root>",
        )
        for xml in cases:
            result = fix_xml_with_text_tags(xml, ["code"])
            expected = "<root><code><![CDATA[hello world]]></code></root>"
            self.assertEqual(expected, result)

    def test_cdata_fallback_plain_closing(self):
        """Fallback to </tag> closing when no ]]> is found in CDATA mode"""
        xml = "<root><code><![CDATA[text</code></root>"
        expected = "<root><code><![CDATA[text]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    # ------------------------------ Nested same-name plain text tags ------------------------------
    def test_normal_mode_nested_same_name_escaped(self):
        """Nested same-name tags in normal mode are escaped as text"""
        xml = "<root><code>outer <code>inner</code> tail</code></root>"
        expected = "<root><code>outer &lt;code&gt;inner&lt;/code&gt; tail</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_cdata_mode_nested_same_name_preserved(self):
        """Nested same-name tags in CDATA mode are preserved as text"""
        xml = "<root><code><![CDATA[before <code>inner</code> after]]></code></root>"
        expected = "<root><code><![CDATA[before <code>inner</code> after]]></code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    # ------------------------------ Namespace support ------------------------------
    def test_namespace_text_tag_recognized(self):
        """Namespaced plain text tags are correctly recognized"""
        xml = "<root><ns:code>a < b</ns:code></root>"
        result = fix_xml_with_text_tags(xml, ["ns:code"])
        self.assertIn("&lt;", result)

    # ------------------------------ Mixed scenarios & edge cases ------------------------------
    def test_mixed_normal_and_text_tags(self):
        """Mixed normal and plain text tags are processed independently without interference"""
        xml = "<root><normal><code>text <div/></code></normal><code>hello</code></root>"
        expected = "<root><normal><code>text &lt;div/&gt;</code></normal><code>hello</code></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, ["code"]), expected)

    def test_multiple_different_text_tags(self):
        """Multiple different plain text tags are processed independently"""
        xml = "<root><code>a < b</code><pre>c > d</pre></root>"
        result = fix_xml_with_text_tags(xml, ["code", "pre"])
        self.assertIn("&lt;", result)
        self.assertIn("&gt;", result)

    def test_text_tag_self_closing_not_processed(self):
        """Self-closing plain text tags do not enter plain text processing mode"""
        xml = "<root><code/></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<code/>", result)

    def test_unicode_content_preserved(self):
        """Unicode/emoji content is fully preserved"""
        xml = "<root><code>こんにちは 🌍 中文测试</code></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("こんにちは 🌍 中文测试", result)

    # ------------------------------ Content integrity & output validity verification ------------------------------
    def test_normal_mode_content_roundtrip(self):
        """Escaped content in normal mode matches original after parsing"""
        xml = "<root><code>if x < 5 && y > 10</code></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        root = ET.fromstring(result)
        self.assertEqual(root.find("code").text, "if x < 5 && y > 10")

    def test_cdata_mode_content_roundtrip(self):
        """Escaped content in CDATA mode matches original after parsing"""
        xml = "<root><code><![CDATA[content]]>inside]]></code></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        root = ET.fromstring(result)
        self.assertEqual(root.find("code").text, "content]]>inside")

    def test_cdata_mode_cdata_inside_roundtrip(self):
        xml = "<A><B><![CDATA[<![CDATA[]]></B></A>"
        result = fix_xml_with_text_tags(xml, [])
        root = ET.fromstring(result)
        self.assertEqual(root.find("B").text, "<![CDATA[")

    def test_output_parseable_by_standard_parser(self):
        """Fixed XML can be parsed by standard XML parser"""
        xml = "<root><a><b>text<code><![CDATA[a < b]]></code></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        # No parsing exception indicates pass
        ET.fromstring(result)

    def test_very_complex_nested_cdata_fix(self):
        """Test repair integrity of extremely complex nested CDATA/code content"""
        this_file = pathlib.Path(__file__).read_text(encoding="utf-8")
        test_xml = """<root><code name="test.py"><![CDATA[%s]]></code></root>""" % (
            this_file.replace(']]]]><![CDATA[>', ']]]]]]><![CDATA[><![CDATA[>')
        )
        result = fix_xml_with_text_tags(test_xml)
        expected = """<root><code name="test.py"><![CDATA[%s]]></code></root>""" % (
            this_file.replace(']]>', ']]]]><![CDATA[>')
        )
        self.assertEqual(expected, result)

    # ------------------------------ New: Automatic escaping for unknown tags ------------------------------
    def test_normal_tag_text_escape_amp(self):
        """Ampersand in normal tag is escaped automatically"""
        xml = "<root><normal>a & b</normal></root>"
        expected = "<root><normal>a &amp; b</normal></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_text_escape_gt(self):
        """Greater-than in normal tag is escaped to &gt;"""
        xml = "<root><normal>a > b</normal></root>"
        expected = "<root><normal>a &gt; b</normal></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_text_preserve_entity(self):
        """Valid entities are not double-escaped in normal tags"""
        xml = "<root><normal>&amp; &lt; &gt;</normal></root>"
        expected = "<root><normal>&amp; &lt; &gt;</normal></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_mixed_content_escape(self):
        """Text around child tags is escaped while child tags remain"""
        xml = "<root><normal>a & b <inner/> c > d</normal></root>"
        expected = "<root><normal>a &amp; b <inner/> c &gt; d</normal></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_multiple_text_blocks(self):
        """Multiple text blocks in a tag are all escaped"""
        xml = "<root><item>first & second <inner/> third > fourth &amp; fifth</item></root>"
        expected = "<root><item>first &amp; second <inner/> third &gt; fourth &amp; fifth</item></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_normal_tag_unclosed_with_special_chars(self):
        """Unclosed normal tag with special chars is escaped and closed automatically"""
        xml = "<root><item>a & b"
        expected = "<root><item>a &amp; b</item></root>"
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_output_parseable_after_auto_escape(self):
        """After auto-escaping, the result is valid XML parseable by ET"""
        xml = "<root><data>a & b < c > d</data></root>"
        result = fix_xml_with_text_tags(xml, [])
        # Should not raise any parse error
        root = ET.fromstring(result)
        self.assertIsNotNone(root)

    def test_normal_tag_text_with_ampersand_in_attr_value(self):
        """Attribute values are not escaped by text escaping"""
        xml = '<root><tag attr="a & b">text</tag></root>'
        expected = '<root><tag attr="a & b">text</tag></root>'
        self.assertEqual(fix_xml_with_text_tags(xml, []), expected)

    def test_mixed_text_tags_and_normal_tags_escaping(self):
        """Text-tags use their dedicated processing, normal tags use auto-escape"""
        xml = "<root><code>if a < b</code><normal>c & d</normal></root>"
        result = fix_xml_with_text_tags(xml, ["code"])
        self.assertIn("<code>if a &lt; b</code>", result)
        self.assertIn("<normal>c &amp; d</normal>", result)


class TestGetXmlTagText(unittest.TestCase):
    """Test cases for get_xml_tag_text function"""

    def test_none_value_returns_empty(self):
        """None input returns empty string"""
        self.assertEqual(get_xml_tag_text(None), "")

    def test_string_value_returned_as_is(self):
        """String input is returned directly"""
        self.assertEqual(get_xml_tag_text("test content"), "test content")

    def test_list_takes_first_element(self):
        """List input takes first element and processes it"""
        self.assertEqual(get_xml_tag_text(["first", "second"]), "first")
        self.assertEqual(get_xml_tag_text([]), "")

    def test_dict_extracts_text_key(self):
        """Dict input extracts value from #text key"""
        self.assertEqual(get_xml_tag_text({"#text": "text content", "@attr": "val"}), "text content")
        self.assertEqual(get_xml_tag_text({"@attr": "val"}), "")

    def test_other_types_return_empty(self):
        """Non-supported types return empty string"""
        self.assertEqual(get_xml_tag_text(123), "")
        self.assertEqual(get_xml_tag_text(True), "")
        self.assertEqual(get_xml_tag_text({"key": "val"}), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
