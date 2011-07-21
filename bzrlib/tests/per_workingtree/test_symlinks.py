# Copyright (C) 2010 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Test symlink support.
"""

import os

from bzrlib import (
    osutils,
    tests,
    workingtree,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree
from bzrlib.tests import (
    features,
    )


class TestSmartAddTree(TestCaseWithWorkingTree):

    # See eg <https://bugs.launchpad.net/bzr/+bug/192859>

    _test_needs_features = [features.SymlinkFeature]

    def test_smart_add_symlink(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/link@', 'target'),
            ])
        tree.smart_add(['tree/link'])
        self.assertIsNot(None, tree.path2id('link'))
        self.assertIs(None, tree.path2id('target'))
        self.assertEqual('symlink',
            tree.kind(tree.path2id('link')))

    def test_smart_add_symlink_pointing_outside(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/link@', '../../../../target'),
            ])
        tree.smart_add(['tree/link'])
        self.assertIsNot(None, tree.path2id('link'))
        self.assertIs(None, tree.path2id('target'))
        self.assertEqual('symlink',
            tree.kind(tree.path2id('link')))

    def test_add_file_under_symlink(self):
        # similar to 
        # https://bugs.launchpad.net/bzr/+bug/192859/comments/3
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/link@', 'dir'),
            ('tree/dir/',),
            ('tree/dir/file', 'content'),
            ])
        self.assertEquals(
            tree.smart_add(['tree/link/file']),
            ([u'dir', u'dir/file'], {}))
        # should add the actual parent directory, not the apparent parent
        # (which is actually a symlink)
        self.assertTrue(tree.path2id('dir/file'))
        self.assertTrue(tree.path2id('dir'))
        self.assertIs(None, tree.path2id('link'))
        self.assertIs(None, tree.path2id('link/file'))


class TestKindChanges(TestCaseWithWorkingTree):

    _test_needs_features = [features.SymlinkFeature]

    def test_symlink_changes_to_dir(self):
        # <https://bugs.launchpad.net/bzr/+bug/192859>:
        # we had some past problems with the workingtree remembering for too
        # long what kind of object was at a particular name; we really
        # shouldn't do that.  Operating on the dirstate through passing
        # inventory deltas rather than mutating the inventory largely avoids
        # that.
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/a@', 'target')])
        tree.smart_add(['tree/a'])
        tree.commit('add symlink')
        os.unlink('tree/a')
        self.build_tree_contents([
            ('tree/a/',),
            ('tree/a/f', 'content'),
            ])
        tree.smart_add(['tree/a/f'])
        tree.commit('change to dir')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEquals([], list(tree.iter_changes(tree.basis_tree())))
        self.assertEquals(
            ['a', 'a/f'], sorted(info[0] for info in tree.list_files()))

    def test_dir_changes_to_symlink(self):
        # <https://bugs.launchpad.net/bzr/+bug/192859>:
        # we had some past problems with the workingtree remembering for too
        # long what kind of object was at a particular name; we really
        # shouldn't do that.  Operating on the dirstate through passing
        # inventory deltas rather than mutating the inventory largely avoids
        # that.
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/a/',),
            ('tree/a/file', 'content'),
            ])
        tree.smart_add(['tree/a'])
        tree.commit('add dir')
        osutils.rmtree('tree/a')
        self.build_tree_contents([
            ('tree/a@', 'target'),
            ])
        tree.commit('change to symlink')


class TestOpenTree(TestCaseWithWorkingTree):

    _test_needs_features = [features.SymlinkFeature]

    def test_open_containing_through_symlink(self):
        self.make_test_tree()
        self.check_open_containing('link/content', 'tree', 'content')
        self.check_open_containing('link/sublink', 'tree', 'sublink')
        # this next one is a bit debatable, but arguably it's better that
        # open_containing is only concerned with opening the tree 
        # and then you can deal with symlinks along the way if you want
        self.check_open_containing('link/sublink/subcontent', 'tree',
            'sublink/subcontent')

    def check_open_containing(self, to_open, expected_tree_name,
        expected_relpath):
        wt, relpath = workingtree.WorkingTree.open_containing(to_open)
        self.assertEquals(relpath, expected_relpath)
        self.assertEndsWith(wt.basedir, expected_tree_name)

    def test_tree_files(self):
        # not strictly a WorkingTree method, but it should be
        # probably the root cause for
        # <https://bugs.launchpad.net/bzr/+bug/128562>
        self.make_test_tree()
        self.check_tree_files(['tree/outerlink'],
            'tree', ['outerlink'])
        self.check_tree_files(['link/outerlink'],
            'tree', ['outerlink'])
        self.check_tree_files(['link/sublink/subcontent'],
            'tree', ['subdir/subcontent'])

    def check_tree_files(self, to_open, expected_tree, expect_paths):
        tree, relpaths = workingtree.WorkingTree.open_containing_paths(to_open)
        self.assertEndsWith(tree.basedir, expected_tree)
        self.assertEquals(expect_paths, relpaths)

    def make_test_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('link@', 'tree'),
            ('tree/outerlink@', '/not/there'),
            ('tree/content', 'hello'),
            ('tree/sublink@', 'subdir'),
            ('tree/subdir/',),
            ('tree/subdir/subcontent', 'subcontent stuff')
            ])
