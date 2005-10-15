#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib
import os

from bzrlib.inventory import ROOT_ID
from bzrlib.errors import BzrCommandError, NotAncestor
from bzrlib.trace import warning, mutter
from collections import deque
from bzrlib.revision import (common_ancestor, MultipleRevisionSources,
                             get_intervening_revisions)
from bzrlib.diff import internal_diff

def _fake_working_revision(branch):
    """Fake a Revision object for the working tree.
    
    This is for the future, to support changesets against the working tree.
    """
    from bzrlib.revision import Revision
    import time
    from bzrlib.osutils import local_time_offset, \
            username

    precursor = branch.last_patch()
    precursor_sha1 = branch.get_revision_sha1(precursor)

    return Revision(timestamp=time.time(),
            timezone=local_time_offset(),
            committer=username(),
            precursor=precursor,
            precursor_sha1=precursor_sha1)

def _create_ancestry_to_rev(branch, ancestor_rev_id, this_rev_id):
    """Return a listing of revisions, tracing from this_rev_id to ancestor_rev_id.

    This attempts to use branch.revision_history() as much as possible. 
    Because for changesets, that is generally what you want to show.
    """
    # This is an optimization, when both target and base
    # exist in the revision history, we should already have
    # a valid listing of revision ancestry.
    rh = branch.revision_history()
    rh_set = set(rh)

    ancestry = set(branch.get_ancestry(this_rev_id))
    if ancestor_rev_id not in ancestry:
        raise NotAncestor(this_rev_id, ancestor_rev_id)
    # First, if ancestor_rev_id is None, then
    # we just need to trace back to the revision history
    # and then return the rest
    if ancestor_rev_id is None:
        if this_rev_id in rh_set:
            rh = rh[:rh.index(this_rev_id)+1]
            rh.reverse()
            rh.append(None)
            return rh

    if ancestor_rev_id in rh_set and this_rev_id in rh_set:
        ancestor_idx = rh.index(ancestor_rev_id)
        this_rev_idx = rh.index(this_rev_id)
        if ancestor_idx > this_rev_idx:
            raise BzrCommandError('Revision {%s} is a child not an ancestor'
                    ' of {%s}' % (ancestor_rev_id, this_rev_id))
        rh_list = rh[ancestor_idx:this_rev_idx+1]
        rh_list.reverse()
        # return rh_list

    # I considered using depth-first search, as it is a little
    # bit less resource intensive, and it should favor generating
    # paths that are the same as revision_history
    # but since breadth-first-search is generally used
    # we will use that
    # 
    # WARNING: In the presence of merges, there are cases where
    # breadth first search will return a very different path
    # than revision_history or depth first search. Imaging the following:
    #
    # rh: A -> B -> C -> D -> E -> F
    #     |                        ^
    #     |                        |
    #     +--> Z ------------------+
    #
    # In this case, Starting with F, looking for A will return
    # A-F for a revision_history search, but breadth-first will
    # return A,Z,F since it is a much shorter path, and with
    # F merging Z, it looks like a shortcut.
    #
    # But since A-F seems to be the more "correct" history
    # for F, we might consider that revision_history should always
    # be consulted first, and if not found there, to use breadth
    # first search.
    checked_rev_ids = set()

    cur_trails = deque([[this_rev_id]])
    
    while len(cur_trails) > 0:
        cur_trail = cur_trails.popleft()
        cur_rev_id = cur_trail[-1]
        if cur_rev_id in checked_rev_ids:
            continue
        checked_rev_ids.add(cur_rev_id)

        if cur_rev_id == ancestor_rev_id:
            return cur_trail

        if cur_rev_id in branch.revision_store:
            rev = branch.get_revision(cur_rev_id)
        else:
            # Should we just continue here?
            warning('Could not find revision for rev: {%s}, unable to'
                    ' trace ancestry.' % cur_rev_id)
            continue

        for p_id in rev.parent_ids:
            if p_id not in checked_rev_ids:
                cur_trails.append(cur_trail + [p_id])

    raise BzrCommandError('Revision id {%s} not an ancestor of {%s}'
            % (ancestor_rev_id, this_rev_id))

class MetaInfoHeader(object):
    """Maintain all of the header information about this
    changeset.
    """

    def __init__(self,
            base_branch, base_rev_id, base_tree,
            target_branch, target_rev_id, target_tree,
            delta,
            starting_rev_id=None,
            full_remove=False, full_rename=False,
            message=None,
            base_label = 'orig', target_label = 'mod'):
        """
        :param full_remove: Include the full-text for a delete
        :param full_rename: Include an add+delete patch for a rename

        """
        self.base_branch = base_branch
        self.base_rev_id = base_rev_id
        self.base_tree = base_tree
        if self.base_rev_id is not None:
            self.base_revision = self.base_branch.get_revision(self.base_rev_id)
        else:
            self.base_revision = None

        self.target_branch = target_branch
        self.target_rev_id = target_rev_id
        self.target_tree = target_tree

        self.delta = delta

        self.starting_rev_id = starting_rev_id

        self.full_remove=full_remove
        self.full_rename=full_rename

        self.base_label = base_label
        self.target_label = target_label

        self.to_file = None
        #self.revno = None
        #self.parent_revno = None

        # These are entries in the header.
        # They will be repeated in the footer,
        # only if they have changed
        self.date = None
        self.committer = None
        self.message = message

        self._get_revision_list()

    def _get_revision_list(self):
        """This generates the list of all revisions from->to.
        It fills out the internal self.revision_list with Revision
        entries which should be in the changeset.
        """
        # Performance, without locking here, a new lock is taken and
        # broken for every revision (6k+ total locks for the bzr.dev tree)
        self.target_branch.lock_read()
        self.base_branch.lock_read()
        try:
            source = MultipleRevisionSources(self.target_branch, self.base_branch)
            if self.starting_rev_id is None:
                self.starting_rev_id = common_ancestor(self.target_rev_id, 
                    self.base_rev_id, source)

            rev_id_list = get_intervening_revisions(self.starting_rev_id,
                self.target_rev_id, source, self.target_branch.revision_history())

            self.revision_list = [source.get_revision(rid) for rid in rev_id_list]
        finally:
            self.base_branch.unlock()
            self.target_branch.unlock()

    def _write(self, txt, key=None, encode=True, indent=1):
        from common import encode as _encode
        if encode:
            def write(txt):
                self.to_file.write(_encode(txt))
        else:
            def write(txt):
                self.to_file.write(txt)
        if indent > 0:
            write('#' + (' ' * indent))
        if key:
            if txt:
                write('%s: %s\n' % (key, txt))
            else:
                write('%s:\n' % key)
        else:
            write('%s\n' % (txt,))

    def write_meta_info(self, to_file):
        """Write out the meta-info portion to the supplied file.

        :param to_file: Write out the meta information to the supplied
                        file
        """
        self.to_file = to_file

        self._write_header()
        self._write_diffs()
        self._write_footer()

    def _write_header(self):
        """Write the stuff that comes before the patches."""
        from common import format_highres_date, get_header
        write = self._write

        for line in get_header():
            write(line)

        # Print out the basic information about the 'target' revision
        rev = self.revision_list[-1]
        write(rev.committer, key='committer')
        self.committer = rev.committer
        self.date = format_highres_date(rev.timestamp, offset=rev.timezone)
        write(self.date, key='date')
        if self.message is None:
            if rev.message is not None:
                self.message = rev.message
        if self.message:
            write('', key='message')
            for line in self.message.split('\n'):
                write(txt=line, indent=4)

        write('') # line with just '#'
        write('', indent=0) # Empty line

    def _write_footer(self):
        """Write the stuff that comes after the patches.

        This is meant to be more meta-information, which people probably don't want
        to read, but which is required for proper bzr operation.
        """
        write = self._write

        # What should we print out for an Empty base revision?
        if len(self.revision_list[0].parent_ids) == 0:
            assumed_base = None
        else:
            assumed_base = self.revision_list[0].parent_ids[0]

        if (self.base_revision is not None 
                and self.base_revision.revision_id != assumed_base):
            base = self.base_revision.revision_id
            write(base, key='base')
            write(self.base_branch.get_revision_sha1(base), key='base sha1')

        self._write_revisions()

    def _write_revisions(self):
        """Not used. Used for writing multiple revisions."""
        from common import format_highres_date, encode

        write = self._write

        for rev in self.revision_list:
            rev_id = rev.revision_id
            write(rev_id, key='revision')
            write(self.target_branch.get_revision_sha1(rev_id),
                    key = 'sha1', indent=4)
            if rev.committer != self.committer:
                write(rev.committer, key='committer', indent=4)
            date = format_highres_date(rev.timestamp, rev.timezone)
            if date != self.date:
                write(date, key='date', indent=4)
            write(rev.inventory_sha1, key='inventory sha1', indent=4)
            if len(rev.parent_ids) > 0:
                write(txt='', key='parents', indent=4)
                for p_id in rev.parent_ids:
                    p_sha1 = self.target_branch.get_revision_sha1(p_id)
                    if p_sha1 is None:
                        warning('Rev id {%s} parent {%s} missing sha hash.'
                                % (rev_id, p_id))
                        write(p_id + '\t' + p_sha1, indent=7)
                    else:
                        write(p_id, indent=7)
            if rev.message and rev.message != self.message:
                write('', key='message', indent=4)
                for line in rev.message.split('\n'):
                    write(line, indent=7)

    def _write_diffs(self):
        """Write out the specific diffs"""
        def pjoin(*args):
            # Only forward slashes in changesets
            return os.path.join(*args).replace('\\', '/')

        def _maybe_diff(old_label, old_path, old_tree, file_id,
                        new_label, new_path, new_tree, text_modified,
                        kind, to_file, diff_file):
            if text_modified:
                new_entry = new_tree.inventory[file_id]
                old_tree.inventory[file_id].diff(diff_file,
                                                 pjoin(old_label, old_path), old_tree,
                                                 pjoin(new_label, new_path), new_entry, 
                                                 new_tree, to_file)
        DEVNULL = '/dev/null'

        diff_file = internal_diff
        # Get the target tree so that we can check for
        # Appropriate text ids.
        rev_id = self.target_rev_id

        new_label = self.target_label
        new_tree = self.target_tree

        old_tree = self.base_tree
        old_label = self.base_label

        write = self._write
        to_file = self.to_file


        def get_rev_id_str(file_id, kind):
            last_changed_rev_id = new_tree.inventory[file_id].revision

            if rev_id != last_changed_rev_id:
                return ' // last-changed:' + last_changed_rev_id
            else:
                return ''

        for path, file_id, kind in self.delta.removed:
            write('=== removed %s %s' % (kind, path), indent=0)
            if self.full_remove:
                old_tree.inventory[file_id].diff(diff_file, pjoin(old_label, path), old_tree,
                                                 DEVNULL, None, None, to_file)
        for path, file_id, kind in self.delta.added:
            write('=== added %s %s // file-id:%s%s' % (kind,
                    path, file_id, get_rev_id_str(file_id, kind)),
                    indent=0)
            new_tree.inventory[file_id].diff(diff_file, pjoin(new_label, path), new_tree,
                                             DEVNULL, None, None, to_file, 
                                             reverse=True)
        for (old_path, new_path, file_id, kind,
             text_modified, meta_modified) in self.delta.renamed:
            # TODO: Handle meta_modified
            #prop_str = get_prop_change(meta_modified)
            write('=== renamed %s %s // %s%s' % (kind,
                    old_path, new_path,
                    get_rev_id_str(file_id, kind)),
                    indent=0)
            if self.full_rename:
                # Looks like a delete + add
                old_tree.inventory[file_id].diff(diff_file, pjoin(old_label, path), old_tree,
                                                 DEVNULL, None, None, to_file)
                new_tree.inventory[file_id].diff(diff_file, pjoin(new_label, path), new_tree,
                                                 DEVNULL, None, None, to_file, 
                                                 reverse=True)
            else:
                _maybe_diff(old_label, old_path, old_tree, file_id,
                            new_label, new_path, new_tree,
                            text_modified, kind, to_file, diff_file)

        for (path, file_id, kind,
             text_modified, meta_modified) in self.delta.modified:
            # TODO: Handle meta_modified
            #prop_str = get_prop_change(meta_modified)
            write('=== modified %s %s%s' % (kind,
                    path, get_rev_id_str(file_id, kind)),
                    indent=0)
            _maybe_diff(old_label, path, old_tree, file_id,
                        new_label, path, new_tree,
                        text_modified, kind, to_file, diff_file)
 

def show_changeset(base_branch, base_rev_id,
        target_branch, target_rev_id,
        starting_rev_id = None,
        to_file=None, include_full_diff=False,
        message=None):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    base_tree = base_branch.revision_tree(base_rev_id)
    target_tree = target_branch.revision_tree(target_rev_id)

    delta = compare_trees(base_tree, target_tree, want_unchanged=False)

    meta = MetaInfoHeader(base_branch, base_rev_id, base_tree,
            target_branch, target_rev_id, target_tree,
            delta,
            starting_rev_id=starting_rev_id,
            full_rename=include_full_diff, full_remove=include_full_diff,
            message=message)
    meta.write_meta_info(to_file)

