# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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


"""Git inventory."""


import stat


from bzrlib import (
    errors,
    inventory,
    osutils,
    ui,
    urlutils,
    )


class GitInventoryEntry(inventory.InventoryEntry):

    def __init__(self, inv, parent_id, hexsha, path, name, executable):
        self.name = name
        self.parent_id = parent_id
        self._inventory = inv
        self._object = None
        self.hexsha = hexsha
        self.path = path
        self.revision = self._inventory.revision_id
        self.executable = executable
        self.file_id = self._inventory.mapping.generate_file_id(path.encode('utf-8'))

    @property
    def object(self):
        if self._object is None:
            self._object = self._inventory.store[self.hexsha]
        return self._object


class GitInventoryFile(GitInventoryEntry):

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryFile, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.kind = 'file'
        self.text_id = None
        self.symlink_target = None

    @property
    def text_sha1(self):
        return osutils.sha_string(self.object.data)

    @property
    def text_size(self):
        return len(self.object.data)

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, sha1=%r, len=%s, revision=%s)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.text_sha1,
                   self.text_size,
                   self.revision))

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def copy(self):
        other = inventory.InventoryFile(self.file_id, self.name, self.parent_id)
        other.executable = self.executable
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.revision = self.revision
        return other


class GitInventoryLink(GitInventoryEntry):

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryLink, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.text_sha1 = None
        self.text_size = None
        self.kind = 'symlink'

    @property
    def symlink_target(self):
        return self.object.data

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def copy(self):
        other = inventory.InventoryLink(self.file_id, self.name, self.parent_id)
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other


class GitInventoryDirectory(GitInventoryEntry):

    def __init__(self, inv, parent_id, hexsha, path, basename, executable):
        super(GitInventoryDirectory, self).__init__(inv, parent_id, hexsha, path, basename, executable)
        self.text_sha1 = None
        self.text_size = None
        self.symlink_target = None
        self.kind = 'directory'
        self._children = None

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'

    @property
    def children(self):
        if self._children is None:
            self._retrieve_children()
        return self._children

    def _retrieve_children(self):
        self._children = {}
        for mode, name, hexsha in self.object.entries():
            basename = name.decode("utf-8")
            child_path = osutils.pathjoin(self.path, basename)
            entry_kind = (mode & 0700000) / 0100000
            fs_mode = mode & 0777
            executable = bool(fs_mode & 0111)
            if entry_kind == 0:
                kind_class = GitInventoryDirectory
            elif entry_kind == 1:
                file_kind = (mode & 070000) / 010000
                if file_kind == 0:
                    kind_class = GitInventoryFile
                elif file_kind == 2:
                    kind_class = GitInventoryLink
                else:
                    raise AssertionError(
                        "Unknown file kind, perms=%o." % (mode,))
            else:
                raise AssertionError(
                    "Unknown blob kind, perms=%r." % (mode,))
            self._children[basename] = kind_class(self._inventory, self.file_id, hexsha, child_path, basename, executable)

    def copy(self):
        other = inventory.InventoryDirectory(self.file_id, self.name, 
                                             self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other


class GitInventory(inventory.Inventory):

    def __init__(self, tree_id, mapping, store, revision_id):
        super(GitInventory, self).__init__(revision_id=revision_id)
        self.store = store
        self.mapping = mapping
        self.root = GitInventoryDirectory(self, None, tree_id, u"", u"", False)

    def _get_ie(self, path):
        parts = path.split("/")
        ie = self.root
        for name in parts:
            ie = ie.children[name] 
        return ie

    def has_filename(self, path):
        try:
            self._get_ie(path)
            return True
        except KeyError:
            return False

    def has_id(self, file_id):
        try:
            self.id2path(file_id)
            return True
        except errors.NoSuchId:
            return False

    def id2path(self, file_id):
        path = self.mapping.parse_file_id(file_id)
        try:
            ie = self._get_ie(path)
            assert ie.path == path
        except KeyError:
            raise errors.NoSuchId(None, file_id)

    def path2id(self, path):
        try:
            return self._get_ie(path).file_id
        except KeyError:
            return None

    def __getitem__(self, file_id):
        if file_id == inventory.ROOT_ID:
            return self.root
        path = self.mapping.parse_file_id(file_id)
        try:
            return self._get_ie(path)
        except KeyError:
            raise errors.NoSuchId(None, file_id)


class GitIndexInventory(inventory.Inventory):
    """Inventory that retrieves its contents from an index file."""

    def __init__(self, basis_inventory, mapping, index):
        super(GitIndexInventory, self).__init__(revision_id=None, root_id=None)
        self.basis_inv = basis_inventory
        self.mapping = mapping
        self.index = index

        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (path, value) in enumerate(self.index.iteritems()):
                pb.update("creating working inventory from index", 
                        i, len(self.index))
                assert isinstance(path, str)
                assert isinstance(value, tuple) and len(value) == 10
                (ctime, mtime, ino, dev, mode, uid, gid, size, sha, flags) = value
                try:
                    old_ie = self.basis_inv._get_ie(path)
                except KeyError:
                    old_ie = None
                if old_ie is None:
                    file_id = self.mapping.generate_file_id(path)
                else:
                    file_id = old_ie.file_id
                if stat.S_ISLNK(mode):
                    kind = 'symlink'
                else:
                    assert stat.S_ISREG(mode)
                    kind = 'file'
                if old_ie is not None and old_ie.hexsha == sha:
                    # Hasn't changed since basis inv
                    ie = old_ie
                else:
                    ie = self.add_path(path, kind, file_id, self.add_parents(path))
                    ie.revision = None
        finally:
            pb.finished()

    def add_parents(self, path):
        dirname, _ = osutils.split(path)
        file_id = self.path2id(dirname)
        if file_id is None:
            if dirname == "":
                parent_fid = None
            else:
                parent_fid = self.add_parents(dirname)
            ie = self.add_path(dirname, 'directory', 
                    self.mapping.generate_file_id(dirname), parent_fid)
            if ie.file_id in self.basis_inv:
                ie.revision = self.basis_inv[ie.file_id].revision
            file_id = ie.file_id
        return file_id

