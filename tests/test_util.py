#    test_util.py -- Testsuite for builddeb util.py
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

try:
    import hashlib as md5
except ImportError:
    import md5
import os
import shutil

from debian_bundle.changelog import Version

from bzrlib.plugins.builddeb.errors import (MissingChangelogError,
                AddChangelogError,
                )
from bzrlib.plugins.builddeb.tests import SourcePackageBuilder
from bzrlib.plugins.builddeb.util import (
                  dget,
                  dget_changes,
                  find_changelog,
                  get_snapshot_revision,
                  lookup_distribution,
                  move_file_if_different,
                  get_parent_dir,
                  recursive_copy,
                  strip_changelog_message,
                  suite_to_distribution,
                  tarball_name,
                  write_if_different,
                  )

from bzrlib import errors as bzr_errors
from bzrlib.tests import (TestCaseWithTransport,
                          TestCaseInTempDir,
                          TestCase,
                          )


class RecursiveCopyTests(TestCaseInTempDir):

    def test_recursive_copy(self):
        os.mkdir('a')
        os.mkdir('b')
        os.mkdir('c')
        os.mkdir('a/d')
        os.mkdir('a/d/e')
        f = open('a/f', 'wb')
        try:
            f.write('f')
        finally:
            f.close()
        os.mkdir('b/g')
        recursive_copy('a', 'b')
        self.failUnlessExists('a')
        self.failUnlessExists('b')
        self.failUnlessExists('c')
        self.failUnlessExists('b/d')
        self.failUnlessExists('b/d/e')
        self.failUnlessExists('b/f')
        self.failUnlessExists('a/d')
        self.failUnlessExists('a/d/e')
        self.failUnlessExists('a/f')


cl_block1 = """\
bzr-builddeb (0.17) unstable; urgency=low

  [ James Westby ]
  * Pass max_blocks=1 when constructing changelogs as that is all that is
    needed currently.

 -- James Westby <jw+debian@jameswestby.net>  Sun, 17 Jun 2007 18:48:28 +0100

"""


class FindChangelogTests(TestCaseWithTransport):

    def write_changelog(self, filename):
        f = open(filename, 'wb')
        try:
            f.write(cl_block1)
            f.write("""\
bzr-builddeb (0.16.2) unstable; urgency=low

  * loosen the dependency on bzr. bzr-builddeb seems to be not be broken
    by bzr version 0.17, so remove the upper bound of the dependency.

 -- Reinhard Tartler <siretart@tauware.de>  Tue, 12 Jun 2007 19:45:38 +0100
""")
        finally:
            f.close()

    def test_find_changelog_std(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, False)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_nomerge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        self.assertRaises(MissingChangelogError, find_changelog, tree, False)

    def test_find_changelog_nochangelog(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        self.assertRaises(MissingChangelogError, find_changelog, tree, False)

    def test_find_changelog_nochangelog_merge(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(MissingChangelogError, find_changelog, tree, True)

    def test_find_changelog_symlink(self):
        """When there was a symlink debian -> . then the code used to break"""
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        os.symlink('.', 'debian')
        tree.add(['debian'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_symlink_naughty(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        f = open('changelog', 'wb')
        try:
            f.write('Naughty, naughty')
        finally:
            f.close()
        tree.add(['changelog', 'debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_changelog_not_added(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        self.assertRaises(AddChangelogError, find_changelog, tree, False)


class StripChangelogMessageTests(TestCase):

    def test_None(self):
        self.assertEqual(strip_changelog_message(None), None)

    def test_no_changes(self):
        self.assertEqual(strip_changelog_message([]), [])

    def test_empty_changes(self):
        self.assertEqual(strip_changelog_message(['']), [])

    def test_removes_leading_whitespace(self):
        self.assertEqual(strip_changelog_message(
                    ['foo', '  bar', '\tbaz', '   bang']),
                    ['foo', 'bar', 'baz', ' bang'])

    def test_removes_star_if_one(self):
        self.assertEqual(strip_changelog_message(['  * foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['\t* foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  + foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  - foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  *  foo']), ['foo'])
        self.assertEqual(strip_changelog_message(['  *  foo', '     bar']),
                ['foo', 'bar'])

    def test_leaves_start_if_multiple(self):
        self.assertEqual(strip_changelog_message(['  * foo', '  * bar']),
                    ['* foo', '* bar'])
        self.assertEqual(strip_changelog_message(['  * foo', '  + bar']),
                    ['* foo', '+ bar'])
        self.assertEqual(strip_changelog_message(
                    ['  * foo', '  bar', '  * baz']),
                    ['* foo', 'bar', '* baz'])


class TarballNameTests(TestCase):

    def test_tarball_name(self):
        self.assertEqual(tarball_name("package", "0.1"),
                "package_0.1.orig.tar.gz")
        self.assertEqual(tarball_name("package", Version("0.1")),
                "package_0.1.orig.tar.gz")


class GetRevisionSnapshotTests(TestCase):

    def test_with_snapshot(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4~bzr30"))

    def test_with_snapshot_plus(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4+bzr30"))

    def test_without_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4"))

    def test_non_numeric_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4~bzra"))

    def test_with_svn_snapshot(self):
        self.assertEquals("svn:4242", get_snapshot_revision("0.4.4~svn4242"))

    def test_with_svn_snapshot_plus(self):
        self.assertEquals("svn:2424", get_snapshot_revision("0.4.4+svn2424"))


class SuiteToDistributionTests(TestCase):

    def _do_lookup(self, target):
        return suite_to_distribution(target)

    def lookup_ubuntu(self, target):
        self.assertEqual(self._do_lookup(target), 'ubuntu')

    def lookup_debian(self, target):
        self.assertEqual(self._do_lookup(target), 'debian')

    def lookup_other(self, target):
        self.assertEqual(self._do_lookup(target), None)

    def test_lookup_ubuntu(self):
        self.lookup_ubuntu('intrepid')
        self.lookup_ubuntu('hardy-proposed')
        self.lookup_ubuntu('gutsy-updates')
        self.lookup_ubuntu('feisty-security')
        self.lookup_ubuntu('dapper-backports')

    def test_lookup_debian(self):
        self.lookup_debian('unstable')
        self.lookup_debian('stable-security')
        self.lookup_debian('testing-proposed-updates')
        self.lookup_debian('etch-backports')

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_other("debian")
        self.lookup_other("ubuntu")


class LookupDistributionTests(SuiteToDistributionTests):

    def _do_lookup(self, target):
        return lookup_distribution(target)

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_debian("debian")
        self.lookup_ubuntu("ubuntu")
        self.lookup_ubuntu("Ubuntu")


class MoveFileTests(TestCaseInTempDir):

    def test_move_file_non_extant(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'b', None)
        self.failIfExists('a')
        self.failUnlessExists('b')

    def test_move_file_samefile(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'a', None)
        self.failUnlessExists('a')

    def test_move_file_same_md5(self):
        self.build_tree(['a'])
        md5sum = md5.md5()
        f = open('a', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        shutil.copy('a', 'b')
        move_file_if_different('a', 'b', md5sum.hexdigest())
        self.failUnlessExists('a')
        self.failUnlessExists('b')

    def test_move_file_diff_md5(self):
        self.build_tree(['a', 'b'])
        md5sum = md5.md5()
        f = open('a', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        a_hexdigest = md5sum.hexdigest()
        md5sum = md5.md5()
        f = open('b', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        b_hexdigest = md5sum.hexdigest()
        self.assertNotEqual(a_hexdigest, b_hexdigest)
        move_file_if_different('a', 'b', a_hexdigest)
        self.failIfExists('a')
        self.failUnlessExists('b')
        md5sum = md5.md5()
        f = open('b', 'rb')
        try:
            md5sum.update(f.read())
        finally:
            f.close()
        self.assertEqual(md5sum.hexdigest(), a_hexdigest)


class WriteFileTests(TestCaseInTempDir):

    def test_write_non_extant(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")

    def test_write_file_same(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")

    def test_write_file_different(self):
        write_if_different("foo", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "foo")
        write_if_different("bar", 'a')
        self.failUnlessExists('a')
        self.check_file_contents('a', "bar")


class DgetTests(TestCaseWithTransport):

    def test_dget_local(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(builder.dsc_name(), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))

    def test_dget_transport(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(self.get_url(builder.dsc_name()), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))

    def test_dget_missing_dsc(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        # No builder.build()
        self.build_tree(["target/"])
        self.assertRaises(bzr_errors.NoSuchFile, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_file(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        os.unlink(builder.tar_name())
        self.build_tree(["target/"])
        self.assertRaises(bzr_errors.NoSuchFile, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_target(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.assertRaises(bzr_errors.NotADirectory, dget,
                self.get_url(builder.dsc_name()), 'target')

    def test_dget_changes(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget_changes(builder.changes_name(), 'target')
        self.failUnlessExists(os.path.join("target", builder.dsc_name()))
        self.failUnlessExists(os.path.join("target", builder.tar_name()))
        self.failUnlessExists(os.path.join("target", builder.diff_name()))
        self.failUnlessExists(os.path.join("target", builder.changes_name()))


class ParentDirTests(TestCase):

    def test_get_parent_dir(self):
        self.assertEqual(get_parent_dir("a"), '')
        self.assertEqual(get_parent_dir("a/"), '')
        self.assertEqual(get_parent_dir("a/b"), 'a')
        self.assertEqual(get_parent_dir("a/b/"), 'a')
        self.assertEqual(get_parent_dir("a/b/c"), 'a/b')
