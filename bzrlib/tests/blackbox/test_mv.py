# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test for 'bzr mv'"""

import os

from bzrlib.tests import TestCaseWithTransport


class TestMove(TestCaseWithTransport):

    def test_mv_modes(self):
        """Test two modes of operation for mv"""
        tree = self.make_branch_and_tree('.')
        files = self.build_tree(['a', 'c', 'subdir/'])
        tree.add(['a', 'c', 'subdir'])

        self.run_bzr('mv', 'a', 'b')
        self.run_bzr('mv', 'b', 'subdir')
        self.run_bzr('mv', 'subdir/b', 'a')
        self.run_bzr('mv', 'a', 'c', 'subdir')
        self.run_bzr('mv', 'subdir/a', 'subdir/newa')

    def test_mv_unversioned(self):
        self.build_tree(['unversioned.txt'])
        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: old name .* is not versioned$"],
            'mv', 'unversioned.txt', 'elsewhere')

    def test_mv_nonexisting(self):
        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: old working file .* does not exist$"],
            'mv', 'doesnotexist', 'somewhereelse')

    def test_mv_unqualified(self):
        self.run_bzr_error(['^bzr: ERROR: missing file argument$'], 'mv')
        
    def test_mv_newly_added(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt'])
        tree.add(['test.txt'])

        self.run_bzr('mv', 'test.txt', 'hello.txt')
        self.failUnlessExists("hello.txt")
        self.failIfExists("test.txt")

    def test_mv_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt', 'sub1/'])
        tree.add(['test.txt'])

        self.run_bzr_error(
            ["^bzr: ERROR: destination u'sub1' is not a versioned directory$"],
            'rename', 'test.txt', 'sub1')
        
        self.run_bzr_error(
            ["^bzr: ERROR: can't determine destination directory id for u'sub1'$"],
            'rename', 'test.txt', 'sub1/hello.txt')
        
        self.run_bzr_error(
            ["^bzr: ERROR: destination u'sub1' is not a versioned directory$"],
            'move', 'test.txt', 'sub1')
    
    def test_mv_dirs(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt', 'sub1/'])
        tree.add(['hello.txt', 'sub1'])

        self.run_bzr('rename', 'sub1', 'sub2')
        self.run_bzr('move', 'hello.txt', 'sub2')

        self.failUnlessExists("sub2")
        self.failUnlessExists("sub2/hello.txt")
        self.failIfExists("sub1")
        self.failIfExists("hello.txt")

        tree.read_working_inventory()
        tree.commit('commit with some things moved to subdirs')

        self.build_tree(['sub1/'])
        tree.add(['sub1'])
        self.run_bzr('move', 'sub2/hello.txt', 'sub1')
        self.failIfExists('sub2/hello.txt')
        self.failUnlessExists('sub1/hello.txt')
        self.run_bzr('move', 'sub2', 'sub1')
        self.failIfExists('sub2')
        self.failUnlessExists('sub1/sub2')

    def test_mv_relative(self): 
        self.build_tree(['sub1/', 'sub1/sub2/', 'sub1/hello.txt'])
        tree = self.make_branch_and_tree('.')
        tree.add(['sub1', 'sub1/sub2', 'sub1/hello.txt'])
        tree.commit('initial tree')

        os.chdir('sub1/sub2')
        self.run_bzr('move', '../hello.txt', '.')
        self.failUnlessExists('./hello.txt')
        tree.read_working_inventory()
        tree.commit('move to parent directory')

        os.chdir('..')

        self.run_bzr('move', 'sub2/hello.txt', '.')
        self.failUnlessExists('hello.txt')
