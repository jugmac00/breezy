#    test_merge_upstream.py -- Blackbox tests for merge-upstream.
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

import os.path

import bzrlib.export

from bzrlib.plugins.builddeb.tests import (
    BuilddebTestCase,
    SourcePackageBuilder,
    )


class Fixture(object):
    """A test fixture."""

    def __init__(self):
        pass

    def setUp(self, test_case):
        test_case.addCleanup(self.tearDown)

    def tearDown(self):
        pass


class Upstream(Fixture):
    """An upstream.
    
    :ivar tree: The tree of the upstream.
    """

    def setUp(self, test_case):
        Fixture.setUp(self, test_case)
        treename = test_case.getUniqueString()
        tree = test_case.make_branch_and_tree(treename)
        filename = test_case.getUniqueString()
        test_case.build_tree(["%s/%s" % (treename, filename)])
        tree.add([filename])
        tree.commit(test_case.getUniqueString())
        self.tree = tree


class ExportedTarball(Fixture):
    """An exported tarball 'release'."""

    def __init__(self, upstream, version):
        self.upstream = upstream
        self.version = version

    def setUp(self, test_case):
        filename = "project-%s.tar.gz" % self.version
        tree = self.upstream.tree.branch.repository.revision_tree(
            self.upstream.tree.branch.last_revision())
        bzrlib.export.export(tree, filename)
        self.tarball = filename


class DHMadePackage(Fixture):
    """A package made via dh-make."""

    def __init__(self, tar, upstream):
        self.tar = tar
        self.upstream = upstream

    def setUp(self, test_case):
        branchpath = test_case.getUniqueString()
        tree = self.upstream.tree.bzrdir.sprout(branchpath).open_workingtree()
        # UGH: spews, because the subprocess output isn't captured. Be nicer to
        # use closer to the metal functions here, but I'm overwhelmed by the
        # API today, and there is a grue.
        test_case.run_bzr(['dh-make', 'package', str(self.tar.version),
            os.path.abspath(self.tar.tarball)], working_dir=branchpath)
        tree.smart_add([tree.basedir])
        tree.commit('debianised.') # Honestly.
        self.tree = tree


class FileMovedReplacedUpstream(Fixture):
    """An upstream that has been changed by moving and replacing a file."""

    def __init__(self, upstream):
        self.upstream = upstream

    def setUp(self, test_case):
        branchpath = test_case.getUniqueString()
        tree = self.upstream.tree.bzrdir.sprout(branchpath).open_workingtree()
        self.tree = tree
        tree.lock_write()
        try:
            newpath = test_case.getUniqueString()
            for child in tree.inventory.root.children.values():
                if child.kind == 'file':
                    oldpath = child.name
            tree.rename_one(oldpath, newpath)
            test_case.build_tree(["%s/%s" % (os.path.basename(tree.basedir),
                oldpath)])
            tree.add([oldpath])
            tree.commit('yo, renaming and replacing')
        finally:
            tree.unlock()



class TestMergeUpstream(BuilddebTestCase):

    def test_merge_upstream_available(self):
        self.run_bzr('merge-upstream --help')

    def make_upstream(self):
        result = Upstream()
        result.setUp(self)
        return result

    def release_upstream(self, upstream):
        tar = ExportedTarball(upstream, version=self.getUniqueInteger())
        tar.setUp(self)
        return tar

    def import_upstream(self, tar, upstream):
        packaging = DHMadePackage(tar, upstream)
        packaging.setUp(self)
        return packaging
        
    def file_moved_replaced_upstream(self, upstream):
        result = FileMovedReplacedUpstream(upstream)
        result.setUp(self)
        return result

    def test_smoke_renamed_file(self):
        # When a file is renamed by upstream, it should still import ok.
        upstream = self.make_upstream()
        rel1 = self.release_upstream(upstream)
        package = self.import_upstream(rel1, upstream)
        changed_upstream = self.file_moved_replaced_upstream(upstream)
        rel2 = self.release_upstream(changed_upstream)
        self.run_bzr(['merge-upstream', '--version', str(rel2.version),
            os.path.abspath(rel2.tarball), changed_upstream.tree.basedir],
            working_dir=package.tree.basedir)

# vim: ts=4 sts=4 sw=4
