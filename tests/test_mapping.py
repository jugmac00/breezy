# -*- coding: utf-8 -*-

# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from errors import InvalidPropertyValue
from mapping import (generate_revision_metadata, parse_revision_metadata, 
                     parse_revid_property, parse_merge_property, BzrSvnMappingv1, BzrSvnMappingv2, 
                          BzrSvnMappingv3, BzrSvnMappingv4, BzrSvnMappingHybrid)
from bzrlib.tests import (TestCase, adapt_tests)
from bzrlib.revision import Revision
from bzrlib.trace import mutter

class MetadataMarshallerTests(TestCase):
    def test_generate_revision_metadata_none(self):
        self.assertEquals("", 
                generate_revision_metadata(None, None, None, None))

    def test_generate_revision_metadata_committer(self):
        self.assertEquals("committer: bla\n", 
                generate_revision_metadata(None, None, "bla", None))

    def test_generate_revision_metadata_timestamp(self):
        self.assertEquals("timestamp: 2005-06-30 17:38:52.350850105 +0000\n", 
                generate_revision_metadata(1120153132.350850105, 0, 
                    None, None))
            
    def test_generate_revision_metadata_properties(self):
        self.assertEquals("properties: \n" + 
                "\tpropbla: bloe\n" +
                "\tpropfoo: bla\n",
                generate_revision_metadata(None, None,
                    None, {"propbla": "bloe", "propfoo": "bla"}))

    def test_parse_revision_metadata_empty(self):
        parse_revision_metadata("", None)

    def test_parse_revision_metadata_committer(self):
        rev = Revision('someid')
        parse_revision_metadata("committer: somebody\n", rev)
        self.assertEquals("somebody", rev.committer)

    def test_parse_revision_metadata_timestamp(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_timestamp_day(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: Thu 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_properties(self):
        rev = Revision('someid')
        parse_revision_metadata("properties: \n" + 
                                "\tfoo: bar\n" + 
                                "\tha: ha\n", rev)
        self.assertEquals({"foo": "bar", "ha": "ha"}, rev.properties)

    def test_parse_revision_metadata_no_colon(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla", rev))

    def test_parse_revision_metadata_specialchar(self):
        rev = Revision('someid')
        parse_revision_metadata("committer: Adeodato Simó <dato@net.com.org.es>", rev)
        self.assertEquals(u"Adeodato Simó <dato@net.com.org.es>", rev.committer)

    def test_parse_revision_metadata_invalid_name(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla: b", rev))

    def test_parse_revid_property(self):
        self.assertEquals((1, "bloe"), parse_revid_property("1 bloe"))

    def test_parse_revid_property_space(self):
        self.assertEquals((42, "bloe bla"), parse_revid_property("42 bloe bla"))

    def test_parse_revid_property_invalid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("blabla"))

    def test_parse_revid_property_empty_revid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("2 "))

    def test_parse_revid_property_newline(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("foo\nbar"))

class ParseMergePropertyTestCase(TestCase):
    def test_parse_merge_space(self):
        self.assertEqual([], parse_merge_property("bla bla"))

    def test_parse_merge_empty(self):
        self.assertEqual([], parse_merge_property(""))

    def test_parse_merge_simple(self):
        self.assertEqual(["bla", "bloe"], parse_merge_property("bla\tbloe"))


class MappingTestAdapter:
    def test_roundtrip_revision(self):
        revid = self.mapping.generate_revision_id("myuuid", 42, "path", "somescheme")
        (uuid, path, revnum, scheme) = self.mapping.parse_revision_id(revid)
        self.assertEquals(uuid, "myuuid")
        self.assertEquals(revnum, 42)
        self.assertEquals(path, "path")
        if scheme is not None:
            self.assertEquals(scheme, "somescheme")


class Mappingv1TestAdapter(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv1


class Mappingv2TestAdapter(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv2


class Mappingv3TestAdapter(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv3


#class Mappingv4TestAdapter(MappingTestAdapter,TestCase):
#    def setUp(self):
#        self.mapping = BzrSvnMappingv4

