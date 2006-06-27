# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import svn.repos
import os
import bzrlib
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

import svn.ra, svn.repos, svn.wc

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    """A test case that provides the ability to build Subversion 
    repositories."""

    def setUp(self):
        super(TestCaseWithSubversionRepository, self).setUp()
        self.client_ctx = svn.client.create_context()

    def make_repository(self, relpath):
        """Create a repository.

        :return: Handle to the repository.
        """
        abspath = os.path.join(self.test_dir, relpath)
        repos_url = "file://%s" % abspath

        repos = svn.repos.create(abspath, '', '', None, None)

        revprop_hook = os.path.join(abspath, "hooks", "pre-revprop-change")

        open(revprop_hook, 'w').write("#!/bin/sh")

        os.chmod(revprop_hook, os.stat(revprop_hook).st_mode | 0111)

        return repos_url

    def make_remote_bzrdir(self, relpath):
        """Create a repository."""

        repos_url = self.make_repository(relpath)

        return BzrDir.open("svn+%s" % repos_url)

    def open_local_bzrdir(self, repos_url, relpath):
        """Open a local BzrDir."""

        self.make_checkout(repos_url, relpath)

        return BzrDir.open(relpath)

    def make_local_bzrdir(self, repos_path, relpath):
        """Create a repository and checkout."""

        repos_url = self.make_repository(repos_path)

        return self.open_local_bzrdir(repos_url, relpath)

    def make_checkout(self, repos_url, relpath):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head

        svn.client.checkout2(repos_url, relpath, 
                rev, rev, True, False, self.client_ctx)

    def client_set_prop(self, path, name, value):
        svn.client.propset2(name, value, path, False, True, self.client_ctx)

    def client_set_revprops(self, url, revnum, name, value):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        svn.client.revprop_set(name, value, url, rev, True, self.client_ctx)

    def client_get_revprop(self, url, revnum, name):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        return svn.client.revprop_get(name, url, rev, self.client_ctx)[0]
        
    def client_commit(self, dir, message=None, recursive=True):
        """Commit current changes in specified working copy.
        
        :param relpath: List of paths to commit.
        """
        olddir = os.path.abspath('.')
        os.chdir(dir)
        info = svn.client.commit3(["."], recursive, False, self.client_ctx)
        os.chdir(olddir)
        return (info.revision, info.date, info.author)

    def client_add(self, relpath, recursive=True):
        """Add specified files to working copy.
        
        :param relpath: Path to the files to add.
        """
        svn.client.add3(relpath, recursive, False, False, self.client_ctx)

    def client_delete(self, relpaths):
        """Remove specified files from working copy.

        :param relpath: Path to the files to remove.
        """
        svn.client.delete2([relpaths], True, self.client_ctx)

    def client_copy(self, oldpath, newpath):
        """Copy file in working copy.

        :param oldpath: Relative path to original file.
        :param newpath: Relative path to new file.
        """
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head
        svn.client.copy3(oldpath, rev, newpath, self.client_ctx)

    def build_tree(self, files):
        """Create a directory tree.
        
        :param files: Dictionary with filenames as keys, contents as 
            values. None as value indicates a directory.
        """
        for f in files:
            if files[f] is None:
                os.mkdir(f)
            else:
                try:
                    os.makedirs(os.path.dirname(f))
                except OSError:
                    pass
                open(f, 'w').write(files[f])

    def make_client_and_bzrdir(self, repospath, clientpath):
        repos_url = self.make_client(repospath, clientpath)

        return BzrDir.open("svn+%s" % repos_url)

    def make_client(self, repospath, clientpath):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        :return: Repository URL.
        """
        repos_url = self.make_repository(repospath)
        self.make_checkout(repos_url, clientpath)
        return repos_url

    def make_ra(self, relpath):
        """Create a repository and a ra connection to it. 
        
        :param relpath: Path to create repository at.
        :return: The ra connection.
        """

        repos_url = self.make_repository(relpath)

        return svn.ra.open2(repos_url, svn.ra.callbacks2_t(), None, None)

    def dumpfile(self, repos):
        """Create a dumpfile for the specified repository.

        :return: File name of the dumpfile.
        """
        raise NotImplementedError(self.dumpfile)

    def open_fs(self, relpath):
        """Open a fs.

        :return: FS.
        """
        repos = svn.repos.open(relpath)

        return svn.repos.fs(repos)


def test_suite():
    from unittest import TestSuite, TestLoader
    
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()

    suite = TestSuite()

    testmod_names = [
            'test_branch', 
            'test_commit',
            'test_fileids', 
            'test_logwalker',
            'test_repos', 
            'test_scheme', 
            'test_transport',
            'test_workingtree']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
