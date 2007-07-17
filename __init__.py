# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""
Support for Subversion branches
"""
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.commands import Command, register_command, display_command, Option
from bzrlib.lazy_import import lazy_import
from bzrlib.trace import warning, mutter
from bzrlib.transport import register_lazy_transport, register_transport_proto
from bzrlib.repository import InterRepository

lazy_import(globals(), """
import commit
import fetch 
import format
import workingtree
""")

# versions ending in 'exp' mean experimental mappings
# versions ending in 'dev' mean development version
__version__ = '0.4.0exp'
COMPATIBLE_BZR_VERSIONS = [(0, 19)]

def check_bzrlib_version(desired):
    """Check that bzrlib is compatible.

    If version is < all compatible version, assume incompatible.
    If version is compatible version + 1, assume compatible, with deprecations
    Otherwise, assume incompatible.
    """
    import bzrlib
    bzrlib_version = bzrlib.version_info[:2]
    if (bzrlib_version in desired or 
        ((bzrlib_version[0], bzrlib_version[1]-1) in desired and 
         bzrlib.version_info[3] == 'dev')):
        return
    if bzrlib_version < desired[0]:
        warning('Installed bzr version %s is too old to be used with bzr-svn'
                ' %s.' % (bzrlib.__version__, __version__))
        # Not using BzrNewError, because it may not exist.
        raise Exception, ('Version mismatch', desired)
    else:
        warning('bzr-svn is not up to date with installed bzr version %s.'
                ' \nThere should be a newer version of bzr-svn available.' 
                % (bzrlib.__version__))
        if not (bzrlib_version[0], bzrlib_version[1]-1) in desired:
            raise Exception, 'Version mismatch'

def check_bzrsvn_version():
    """Warn about use of experimental mappings."""
    if __version__.endswith("exp"):
        warning('version of bzr-svn is experimental; output may change between revisions')

def check_subversion_version():
    """Check that Subversion is compatible.

    """
    import svn.delta
    if not hasattr(svn.delta, 'svn_delta_invoke_txdelta_window_handler'):
        warning('Installed Subversion version does not have updated Python '
                'bindings. See the bzr-svn README for details.')
        raise bzrlib.errors.BzrError("incompatible python subversion bindings")

def check_versions():
    check_bzrlib_version(COMPATIBLE_BZR_VERSIONS)
    check_subversion_version()
    check_bzrsvn_version()

register_transport_proto('svn+ssh://', 
    help="Access using the Subversion smart server tunneled over SSH.")
register_transport_proto('svn+file://', 
    help="Access of local Subversion repositories.")
register_transport_proto('svn+http://',
    help="Access of Subversion smart servers over HTTP.")
register_transport_proto('svn+https://',
    help="Access of Subversion smart servers over secure HTTP.")
register_transport_proto('svn://', 
    help="Access using the Subversion smart server.")
register_lazy_transport('svn://', 'bzrlib.plugins.svn.transport', 
                        'SvnRaTransport')
register_lazy_transport('svn+', 'bzrlib.plugins.svn.transport', 
                        'SvnRaTransport')

BzrDirFormat.register_control_format(format.SvnFormat)
BzrDirFormat.register_control_format(workingtree.SvnWorkingTreeDirFormat)

versions_checked = False
def lazy_check_versions():
    global versions_checked
    if versions_checked:
        return
    versions_checked = True
    check_versions()

InterRepository.register_optimiser(fetch.InterFromSvnRepository)
InterRepository.register_optimiser(commit.InterToSvnRepository)

def get_scheme(schemename):
    """Parse scheme identifier and return a branching scheme."""
    from scheme import BranchingScheme
    from bzrlib.errors import BzrCommandError
    
    ret = BranchingScheme.find_scheme(schemename)
    if ret is None:
        raise BzrCommandError('No such branching scheme %r' % schemename)
    return ret


class cmd_svn_import(Command):
    """Convert a Subversion repository to a Bazaar repository.
    
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = [Option('trees', help='Create working trees.'),
                     Option('standalone', help='Create standalone branches.'),
                     Option('all', 
                         help='Convert all revisions, even those not in '
                              'current branch history (forbids --standalone).'),
                     Option('scheme', type=get_scheme,
                         help='Branching scheme (none, trunk, ...).')]

    @display_command
    def run(self, from_location, to_location=None, trees=False, 
            standalone=False, scheme=None, all=False):
        from bzrlib.repository import Repository
        from convert import convert_repository
        import os
        from scheme import TrunkBranchingScheme

        if to_location is None:
            to_location = os.path.basename(from_location.rstrip("/\\"))

        if all:
            standalone = False

        if os.path.isfile(from_location):
            from convert import load_dumpfile
            import tempfile
            tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
            mutter('loading dumpfile %r to %r' % (from_location, tmp_repos))
            load_dumpfile(from_location, tmp_repos)
            from_location = tmp_repos
        else:
            tmp_repos = None

        from_repos = Repository.open(from_location)

        convert_repository(from_repos, to_location, scheme, not standalone, 
                trees, all)

        if tmp_repos is not None:
            from bzrlib import osutils
            osutils.rmtree(tmp_repos)


register_command(cmd_svn_import)

class cmd_svn_upgrade(Command):
    """Upgrade revisions mapped from Subversion in a Bazaar branch.
    
    This will change the revision ids of revisions whose parents 
    were mapped from svn revisions.
    """
    takes_args = ['svn_repository?']
    takes_options = ['verbose']

    @display_command
    def run(self, svn_repository=None, verbose=False):
        from upgrade import upgrade_branch
        from bzrlib.branch import Branch
        from bzrlib.errors import NoWorkingTree, BzrCommandError
        from bzrlib.repository import Repository
        from bzrlib.workingtree import WorkingTree
        try:
            wt_to = WorkingTree.open(".")
            branch_to = wt_to.branch
        except NoWorkingTree:
            wt_to = None
            branch_to = Branch.open(".")

        stored_loc = branch_to.get_parent()
        if svn_repository is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                import bzrlib.urlutils as urlutils
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                svn_repository = Branch.open(stored_loc).repository
        else:
            svn_repository = Repository.open(svn_repository)

        upgrade_branch(branch_to, svn_repository, allow_changes=True, 
                       verbose=verbose)

        if wt_to is not None:
            wt_to.set_last_revision(branch_to.last_revision())

register_command(cmd_svn_upgrade)

class cmd_svn_push_new(Command):
    """Create a new branch in Subversion.
    
    This command is experimental and will be removed in the future.
    """
    takes_args = ['location']
    takes_options = ['revision']

    def run(self, location, revision=None):
        from bzrlib.bzrdir import BzrDir
        from bzrlib.branch import Branch
        bzrdir = BzrDir.open(location)
        branch = Branch.open(".")
        if revision is not None:
            if len(revision) > 1:
                raise errors.BzrCommandError(
                    'bzr svn-push-new --revision takes exactly one revision' 
                    ' identifier')
            revision_id = revision[0].in_history(branch).rev_id
        else:
            revision_id = None
        bzrdir.import_branch(branch, revision_id)

register_command(cmd_svn_push_new)


def test_suite():
    from unittest import TestSuite
    import tests
    suite = TestSuite()
    suite.addTest(tests.test_suite())
    return suite

if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
elif __name__ != 'bzrlib.plugins.svn':
    raise ImportError('The Subversion plugin must be installed as'
                      ' bzrlib.plugins.svn not %s' % __name__)
else:
    import os, sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
