#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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

from sets import Set

from trace import mutter
from errors import BzrError



def _diff_one(oldlines, newlines, to_file, **kw):
    import difflib
    
    # FIXME: difflib is wrong if there is no trailing newline.
    # The syntax used by patch seems to be "\ No newline at
    # end of file" following the last diff line from that
    # file.  This is not trivial to insert into the
    # unified_diff output and it might be better to just fix
    # or replace that function.

    # In the meantime we at least make sure the patch isn't
    # mangled.


    # Special workaround for Python2.3, where difflib fails if
    # both sequences are empty.
    if not oldlines and not newlines:
        return

    nonl = False

    if oldlines and (oldlines[-1][-1] != '\n'):
        oldlines[-1] += '\n'
        nonl = True
    if newlines and (newlines[-1][-1] != '\n'):
        newlines[-1] += '\n'
        nonl = True

    ud = difflib.unified_diff(oldlines, newlines, **kw)

    # work-around for difflib being too smart for its own good
    # if /dev/null is "1,0", patch won't recognize it as /dev/null
    if not oldlines:
        ud = list(ud)
        ud[2] = ud[2].replace('-1,0', '-0,0')
    elif not newlines:
        ud = list(ud)
        ud[2] = ud[2].replace('+1,0', '+0,0')

    to_file.writelines(ud)
    if nonl:
        print >>to_file, "\\ No newline at end of file"
    print >>to_file


def show_diff(b, revision, file_list):
    import sys

    if file_list:
        raise NotImplementedError('diff on restricted files broken at the moment')
    
    if revision == None:
        old_tree = b.basis_tree()
    else:
        old_tree = b.revision_tree(b.lookup_revision(revision))
        
    new_tree = b.working_tree()

    # TODO: Options to control putting on a prefix or suffix, perhaps as a format string
    old_label = ''
    new_label = ''

    DEVNULL = '/dev/null'
    # Windows users, don't panic about this filename -- it is a
    # special signal to GNU patch that the file should be created or
    # deleted respectively.

    # TODO: Generation of pseudo-diffs for added/deleted files could
    # be usefully made into a much faster special case.

    delta = compare_trees(old_tree, new_tree, want_unchanged=False)

    for path, file_id, kind in delta.removed:
        print '*** removed %s %r' % (kind, path)
        if kind == 'file':
            _diff_one(old_tree.get_file(file_id).readlines(),
                   [],
                   sys.stdout,
                   fromfile=old_label + path,
                   tofile=DEVNULL)

    for path, file_id, kind in delta.added:
        print '*** added %s %r' % (kind, path)
        if kind == 'file':
            _diff_one([],
                   new_tree.get_file(file_id).readlines(),
                   sys.stdout,
                   fromfile=DEVNULL,
                   tofile=new_label + path)

    for old_path, new_path, file_id, kind, text_modified in delta.renamed:
        print '*** renamed %s %r => %r' % (kind, old_path, new_path)
        if text_modified:
            _diff_one(old_tree.get_file(file_id).readlines(),
                   new_tree.get_file(file_id).readlines(),
                   sys.stdout,
                   fromfile=old_label + old_path,
                   tofile=new_label + new_path)

    for path, file_id, kind in delta.modified:
        print '*** modified %s %r' % (kind, path)
        if kind == 'file':
            _diff_one(old_tree.get_file(file_id).readlines(),
                   new_tree.get_file(file_id).readlines(),
                   sys.stdout,
                   fromfile=old_label + path,
                   tofile=new_label + path)



class TreeDelta:
    """Describes changes from one tree to another.

    Contains four lists:

    added
        (path, id, kind)
    removed
        (path, id, kind)
    renamed
        (oldpath, newpath, id, kind, text_modified)
    modified
        (path, id, kind)
    unchanged
        (path, id, kind)

    Each id is listed only once.

    Files that are both modified and renamed are listed only in
    renamed, with the text_modified flag true.

    The lists are normally sorted when the delta is created.
    """
    def __init__(self):
        self.added = []
        self.removed = []
        self.renamed = []
        self.modified = []
        self.unchanged = []

    def show(self, to_file, show_ids=False, show_unchanged=False):
        def show_list(files):
            for path, fid, kind in files:
                if kind == 'directory':
                    path += '/'
                elif kind == 'symlink':
                    path += '@'
                    
                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, ' ', path
            
        if self.removed:
            print >>to_file, 'removed:'
            show_list(self.removed)
                
        if self.added:
            print >>to_file, 'added:'
            show_list(self.added)

        if self.renamed:
            print >>to_file, 'renamed:'
            for oldpath, newpath, fid, kind, text_modified in self.renamed:
                if show_ids:
                    print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                else:
                    print >>to_file, '  %s => %s' % (oldpath, newpath)
                    
        if self.modified:
            print >>to_file, 'modified:'
            show_list(self.modified)
            
        if show_unchanged and self.unchanged:
            print >>to_file, 'unchanged:'
            show_list(self.unchanged)



def compare_trees(old_tree, new_tree, want_unchanged):
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    delta = TreeDelta()
    mutter('start compare_trees')
    for file_id in old_tree:
        if file_id in new_tree:
            kind = old_inv.get_file_kind(file_id)
            assert kind == new_inv.get_file_kind(file_id)
            
            assert kind in ('file', 'directory', 'symlink', 'root_directory'), \
                   'invalid file kind %r' % kind

            if kind == 'root_directory':
                continue
            
            old_path = old_inv.id2path(file_id)
            new_path = new_inv.id2path(file_id)

            if kind == 'file':
                old_sha1 = old_tree.get_file_sha1(file_id)
                new_sha1 = new_tree.get_file_sha1(file_id)
                text_modified = (old_sha1 != new_sha1)
            else:
                ## mutter("no text to check for %r %r" % (file_id, kind))
                text_modified = False

            # TODO: Can possibly avoid calculating path strings if the
            # two files are unchanged and their names and parents are
            # the same and the parents are unchanged all the way up.
            # May not be worthwhile.
            
            if old_path != new_path:
                delta.renamed.append((old_path, new_path, file_id, kind,
                                      text_modified))
            elif text_modified:
                delta.modified.append((new_path, file_id, kind))
            elif want_unchanged:
                delta.unchanged.append((new_path, file_id, kind))
        else:
            delta.removed.append((old_inv.id2path(file_id), file_id, kind))

    mutter('start looking for new files')
    for file_id in new_inv:
        if file_id in old_inv:
            continue
        kind = new_inv.get_file_kind(file_id)
        delta.added.append((new_inv.id2path(file_id), file_id, kind))
            
    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()
    delta.modified.sort()
    delta.unchanged.sort()

    return delta
