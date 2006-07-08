# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the EmptyTree class."""

import bzrlib
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tree import EmptyTree


class TestTreeWithCommits(TestCaseWithTransport):

    def test_empty_no_unknowns(self):
        self.assertEqual([], list(EmptyTree().unknowns()))

    def test_no_conflicts(self):
        self.assertEqual([], list(EmptyTree().conflicts()))

    def test_parents(self):
        self.assertEqual([], EmptyTree().get_parent_ids())
