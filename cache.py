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

"""Map from Git sha's to Bazaar objects."""

from dulwich.objects import (
    sha_to_hex,
    hex_to_sha,
    )
import os
import threading

from dulwich.objects import (
    ShaFile,
    )

import bzrlib
from bzrlib import (
    btree_index as _mod_btree_index,
    index as _mod_index,
    osutils,
    registry,
    trace,
    versionedfile,
    )
from bzrlib.transport import (
    get_transport,
    )


def get_cache_dir():
    try:
        from xdg.BaseDirectory import xdg_cache_home
    except ImportError:
        from bzrlib.config import config_dir
        ret = os.path.join(config_dir(), "git")
    else:
        ret = os.path.join(xdg_cache_home, "bazaar", "git")
    if not os.path.isdir(ret):
        os.makedirs(ret)
    return ret


def get_remote_cache_transport(repository):
    """Retrieve the transport to use when accessing (unwritable) remote 
    repositories.
    """
    uuid = getattr(repository, "uuid", None)
    if uuid is None:
        path = get_cache_dir()
    else:
        path = os.path.join(get_cache_dir(), uuid)
        if not os.path.isdir(path):
            os.mkdir(path)
    return get_transport(path)


def check_pysqlite_version(sqlite3):
    """Check that sqlite library is compatible.

    """
    if (sqlite3.sqlite_version_info[0] < 3 or
            (sqlite3.sqlite_version_info[0] == 3 and
             sqlite3.sqlite_version_info[1] < 3)):
        trace.warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

try:
    try:
        import sqlite3
        check_pysqlite_version(sqlite3)
    except (ImportError, bzrlib.errors.BzrError), e:
        from pysqlite2 import dbapi2 as sqlite3
        check_pysqlite_version(sqlite3)
except:
    trace.warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 '
            'module')
    raise bzrlib.errors.BzrError("missing sqlite library")


_mapdbs = threading.local()
def mapdbs():
    """Get a cache for this thread's db connections."""
    try:
        return _mapdbs.cache
    except AttributeError:
        _mapdbs.cache = {}
        return _mapdbs.cache


class GitShaMap(object):
    """Git<->Bzr revision id mapping database."""

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.
        :param sha: Git object sha
        :return: list with (type, type_data) tuples with type_data:
            commit: revid, tree_sha, verifiers
            blob: fileid, revid
            tree: fileid, revid
        """
        raise NotImplementedError(self.lookup_git_sha)

    def lookup_blob_id(self, file_id, revision):
        """Retrieve a Git blob SHA by file id.

        :param file_id: File id of the file/symlink
        :param revision: revision in which the file was last changed.
        """
        raise NotImplementedError(self.lookup_blob_id)

    def lookup_tree_id(self, file_id, revision):
        """Retrieve a Git tree SHA by file id.
        """
        raise NotImplementedError(self.lookup_tree_id)

    def lookup_commit(self, revid):
        """Retrieve a Git commit SHA by Bazaar revision id.
        """
        raise NotImplementedError(self.lookup_commit)

    def revids(self):
        """List the revision ids known."""
        raise NotImplementedError(self.revids)

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present."""
        present_revids = set(self.revids())
        if not isinstance(revids, set):
            revids = set(revids)
        return revids - present_revids

    def sha1s(self):
        """List the SHA1s."""
        raise NotImplementedError(self.sha1s)

    def start_write_group(self):
        """Start writing changes."""

    def commit_write_group(self):
        """Commit any pending changes."""

    def abort_write_group(self):
        """Abort any pending changes."""


class ContentCache(object):
    """Object that can cache Git objects."""

    def add(self, object):
        """Add an object."""
        raise NotImplementedError(self.add)

    def add_multi(self, objects):
        """Add multiple objects."""
        for obj in objects:
            self.add(obj)

    def __getitem__(self, sha):
        """Retrieve an item, by SHA."""
        raise NotImplementedError(self.__getitem__)


class BzrGitCacheFormat(object):
    """Bazaar-Git Cache Format."""

    def get_format_string(self):
        """Return a single-line unique format string for this cache format."""
        raise NotImplementedError(self.get_format_string)

    def open(self, transport):
        """Open this format on a transport."""
        raise NotImplementedError(self.open)

    def initialize(self, transport):
        """Create a new instance of this cache format at transport."""
        transport.put_bytes('format', self.get_format_string())

    @classmethod
    def from_transport(self, transport):
        """Open a cache file present on a transport, or initialize one.

        :param transport: Transport to use
        :return: A BzrGitCache instance
        """
        try:
            format_name = transport.get_bytes('format')
            format = formats.get(format_name)
        except bzrlib.errors.NoSuchFile:
            format = formats.get('default')
            format.initialize(transport)
        return format.open(transport)

    @classmethod
    def from_repository(cls, repository):
        """Open a cache file for a repository.

        This will use the repository's transport to store the cache file, or
        use the users global cache directory if the repository has no 
        transport associated with it.

        :param repository: Repository to open the cache for
        :return: A `BzrGitCache`
        """
        from bzrlib.transport.local import LocalTransport
        repo_transport = getattr(repository, "_transport", None)
        if repo_transport is not None and isinstance(repo_transport, LocalTransport):
            # Even if we don't write to this repo, we should be able
            # to update its cache.
            repo_transport = remove_readonly_transport_decorator(repo_transport)
            try:
                repo_transport.mkdir('git')
            except bzrlib.errors.FileExists:
                pass
            transport = repo_transport.clone('git')
        else:
            transport = get_remote_cache_transport(repository)
        return cls.from_transport(transport)


class CacheUpdater(object):
    """Base class for objects that can update a bzr-git cache."""

    def add_object(self, obj, ie, path):
        """Add an object.

        :param obj: Object type ("commit", "blob" or "tree")
        :param ie: Inventory entry (for blob/tree) or testament_sha in case
            of commit
        :param path: Path of the object (optional)
        """
        raise NotImplementedError(self.add_object)

    def finish(self):
        raise NotImplementedError(self.finish)


class BzrGitCache(object):
    """Caching backend."""

    def __init__(self, idmap, content_cache, cache_updater_klass):
        self.idmap = idmap
        self.content_cache = content_cache
        self._cache_updater_klass = cache_updater_klass

    def get_updater(self, rev):
        """Update an object that implements the CacheUpdater interface for 
        updating this cache.
        """
        return self._cache_updater_klass(self, rev)


DictBzrGitCache = lambda: BzrGitCache(DictGitShaMap(), None, DictCacheUpdater)


class DictCacheUpdater(CacheUpdater):
    """Cache updater for dict-based caches."""

    def __init__(self, cache, rev):
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, ie, path):
        if obj.type_name == "commit":
            self._commit = obj
            assert type(ie) is dict
            key = self.revid
            type_data = (self.revid, self._commit.tree, ie)
            self.cache.idmap._by_revid[self.revid] = obj.id
        elif obj.type_name in ("blob", "tree"):
            if ie is not None:
                if obj.type_name == "blob":
                    revision = ie.revision
                else:
                    revision = self.revid
                key = type_data = (ie.file_id, revision)
                self.cache.idmap._by_fileid.setdefault(type_data[1], {})[type_data[0]] = obj.id
        else:
            raise AssertionError
        entry = (obj.type_name, type_data)
        self.cache.idmap._by_sha.setdefault(obj.id, {})[key] = entry

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


class DictGitShaMap(GitShaMap):
    """Git SHA map that uses a dictionary."""

    def __init__(self):
        self._by_sha = {}
        self._by_fileid = {}
        self._by_revid = {}

    def lookup_blob_id(self, fileid, revision):
        return self._by_fileid[revision][fileid]

    def lookup_git_sha(self, sha):
        for entry in self._by_sha[sha].itervalues():
            yield entry

    def lookup_tree_id(self, fileid, revision):
        return self._by_fileid[revision][fileid]

    def lookup_commit(self, revid):
        return self._by_revid[revid]

    def revids(self):
        for key, entries in self._by_sha.iteritems():
            for (type, type_data) in entries.values():
                if type == "commit":
                    yield type_data[0]

    def sha1s(self):
        return self._by_sha.iterkeys()


class SqliteCacheUpdater(CacheUpdater):

    def __init__(self, cache, rev):
        self.cache = cache
        self.db = self.cache.idmap.db
        self.revid = rev.revision_id
        self._commit = None
        self._trees = []
        self._blobs = []

    def add_object(self, obj, ie, path):
        if obj.type_name == "commit":
            self._commit = obj
            self._testament3_sha1 = ie.get("testament3-sha1")
            assert type(ie) is dict
        elif obj.type_name == "tree":
            if ie is not None:
                self._trees.append((obj.id, ie.file_id, self.revid))
        elif obj.type_name == "blob":
            if ie is not None:
                self._blobs.append((obj.id, ie.file_id, ie.revision))
        else:
            raise AssertionError

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        self.db.executemany(
            "replace into trees (sha1, fileid, revid) values (?, ?, ?)",
            self._trees)
        self.db.executemany(
            "replace into blobs (sha1, fileid, revid) values (?, ?, ?)",
            self._blobs)
        self.db.execute(
            "replace into commits (sha1, revid, tree_sha, testament3_sha1) values (?, ?, ?, ?)",
            (self._commit.id, self.revid, self._commit.tree, self._testament3_sha1))
        return self._commit


SqliteBzrGitCache = lambda p: BzrGitCache(SqliteGitShaMap(p), None, SqliteCacheUpdater)


class SqliteGitCacheFormat(BzrGitCacheFormat):

    def get_format_string(self):
        return 'bzr-git sha map version 1 using sqlite\n'

    def open(self, transport):
        try:
            basepath = transport.local_abspath(".")
        except bzrlib.errors.NotLocalUrl:
            basepath = get_cache_dir()
        return SqliteBzrGitCache(os.path.join(basepath, "idmap.db"))


class SqliteGitShaMap(GitShaMap):
    """Bazaar GIT Sha map that uses a sqlite database for storage."""

    def __init__(self, path=None):
        self.path = path
        if path is None:
            self.db = sqlite3.connect(":memory:")
        else:
            if not mapdbs().has_key(path):
                mapdbs()[path] = sqlite3.connect(path)
            self.db = mapdbs()[path]
        self.db.text_factory = str
        self.db.executescript("""
        create table if not exists commits(
            sha1 text not null check(length(sha1) == 40),
            revid text not null,
            tree_sha text not null check(length(tree_sha) == 40)
        );
        create index if not exists commit_sha1 on commits(sha1);
        create unique index if not exists commit_revid on commits(revid);
        create table if not exists blobs(
            sha1 text not null check(length(sha1) == 40),
            fileid text not null,
            revid text not null
        );
        create index if not exists blobs_sha1 on blobs(sha1);
        create unique index if not exists blobs_fileid_revid on blobs(fileid, revid);
        create table if not exists trees(
            sha1 text unique not null check(length(sha1) == 40),
            fileid text not null,
            revid text not null
        );
        create unique index if not exists trees_sha1 on trees(sha1);
        create unique index if not exists trees_fileid_revid on trees(fileid, revid);
""")
        try:
            self.db.executescript(
                "ALTER TABLE commits ADD testament3_sha1 TEXT;")
        except sqlite3.OperationalError:
            pass # Column already exists.

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.path)

    def lookup_commit(self, revid):
        cursor = self.db.execute("select sha1 from commits where revid = ?", 
            (revid,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        raise KeyError

    def commit_write_group(self):
        self.db.commit()

    def lookup_blob_id(self, fileid, revision):
        row = self.db.execute("select sha1 from blobs where fileid = ? and revid = ?", (fileid, revision)).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_tree_id(self, fileid, revision):
        row = self.db.execute("select sha1 from trees where fileid = ? and revid = ?", (fileid, revision)).fetchone()
        if row is not None:
            return row[0]
        raise KeyError(fileid)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            commit: revid, tree sha, verifiers
            tree: fileid, revid
            blob: fileid, revid
        """
        found = False
        cursor = self.db.execute("select revid, tree_sha, testament3_sha1 from commits where sha1 = ?", (sha,))
        for row in cursor.fetchall():
            found = True
            if row[2] is not None:
                verifiers = {"testament3-sha1": row[2]}
            else:
                verifiers = {}
            yield ("commit", (row[0], row[1], verifiers))
        cursor = self.db.execute("select fileid, revid from blobs where sha1 = ?", (sha,))
        for row in cursor.fetchall():
            found = True
            yield ("blob", row)
        cursor = self.db.execute("select fileid, revid from trees where sha1 = ?", (sha,))
        for row in cursor.fetchall():
            found = True
            yield ("tree", row)
        if not found:
            raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        return (row for (row,) in self.db.execute("select revid from commits"))

    def sha1s(self):
        """List the SHA1s."""
        for table in ("blobs", "commits", "trees"):
            for (sha,) in self.db.execute("select sha1 from %s" % table):
                yield sha


class TdbCacheUpdater(CacheUpdater):
    """Cache updater for tdb-based caches."""

    def __init__(self, cache, rev):
        self.cache = cache
        self.db = cache.idmap.db
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []

    def add_object(self, obj, ie, path):
        sha = obj.sha().digest()
        if obj.type_name == "commit":
            self.db["commit\0" + self.revid] = "\0".join((sha, obj.tree))
            assert type(ie) is dict, "was %r" % ie
            type_data = (self.revid, obj.tree)
            try:
                type_data += (ie["testament3-sha1"],)
            except KeyError:
                pass
            self._commit = obj
        elif obj.type_name == "blob":
            if ie is None:
                return
            self.db["\0".join(("blob", ie.file_id, ie.revision))] = sha
            type_data = (ie.file_id, ie.revision)
        elif obj.type_name == "tree":
            if ie is None:
                return
            type_data = (ie.file_id, self.revid)
        else:
            raise AssertionError
        entry = "\0".join((obj.type_name, ) + type_data) + "\n"
        key = "git\0" + sha
        try:
            oldval = self.db[key]
        except KeyError:
            self.db[key] = entry
        else:
            if oldval[-1] != "\n":
                self.db[key] = "".join([oldval, "\n", entry])
            else:
                self.db[key] = "".join([oldval, entry])

    def finish(self):
        if self._commit is None:
            raise AssertionError("No commit object added")
        return self._commit


TdbBzrGitCache = lambda p: BzrGitCache(TdbGitShaMap(p), None, TdbCacheUpdater)


class TdbGitCacheFormat(BzrGitCacheFormat):
    """Cache format for tdb-based caches."""

    def get_format_string(self):
        return 'bzr-git sha map version 3 using tdb\n'

    def open(self, transport):
        try:
            basepath = transport.local_abspath(".").encode(osutils._fs_enc)
        except bzrlib.errors.NotLocalUrl:
            basepath = get_cache_dir()
        assert isinstance(basepath, str)
        try:
            return TdbBzrGitCache(os.path.join(basepath, "idmap.tdb"))
        except ImportError:
            raise ImportError(
                "Unable to open existing bzr-git cache because 'tdb' is not "
                "installed.")


class TdbGitShaMap(GitShaMap):
    """SHA Map that uses a TDB database.

    Entries:

    "git <sha1>" -> "<type> <type-data1> <type-data2>"
    "commit revid" -> "<sha1> <tree-id>"
    "tree fileid revid" -> "<sha1>"
    "blob fileid revid" -> "<sha1>"
    """

    TDB_MAP_VERSION = 3
    TDB_HASH_SIZE = 50000

    def __init__(self, path=None):
        import tdb
        self.path = path
        if path is None:
            self.db = {}
        else:
            assert isinstance(path, str)
            if not mapdbs().has_key(path):
                mapdbs()[path] = tdb.Tdb(path, self.TDB_HASH_SIZE, tdb.DEFAULT,
                                          os.O_RDWR|os.O_CREAT)
            self.db = mapdbs()[path]
        try:
            if int(self.db["version"]) not in (2, 3):
                trace.warning("SHA Map is incompatible (%s -> %d), rebuilding database.",
                              self.db["version"], self.TDB_MAP_VERSION)
                self.db.clear()
        except KeyError:
            pass
        self.db["version"] = str(self.TDB_MAP_VERSION)

    def start_write_group(self):
        """Start writing changes."""
        self.db.transaction_start()

    def commit_write_group(self):
        """Commit any pending changes."""
        self.db.transaction_commit()

    def abort_write_group(self):
        """Abort any pending changes."""
        self.db.transaction_cancel()

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.path)

    def lookup_commit(self, revid):
        try:
            return sha_to_hex(self.db["commit\0" + revid][:20])
        except KeyError:
            raise KeyError("No cache entry for %r" % revid)

    def lookup_blob_id(self, fileid, revision):
        return sha_to_hex(self.db["\0".join(("blob", fileid, revision))])

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            commit: revid, tree sha
            blob: fileid, revid
            tree: fileid, revid
        """
        if len(sha) == 40:
            sha = hex_to_sha(sha)
        value = self.db["git\0" + sha]
        for data in value.splitlines():
            data = data.split("\0")
            if data[0] == "commit":
                if len(data) == 3:
                    yield (data[0], (data[1], data[2], {}))
                else:
                    yield (data[0], (data[1], data[2], {"testament3-sha1": data[3]}))
            elif data[0] in ("tree", "blob"):
                yield (data[0], tuple(data[1:]))
            else:
                raise AssertionError("unknown type %r" % data[0])

    def missing_revisions(self, revids):
        ret = set()
        for revid in revids:
            if self.db.get("commit\0" + revid) is None:
                ret.add(revid)
        return ret

    def revids(self):
        """List the revision ids known."""
        for key in self.db.iterkeys():
            if key.startswith("commit\0"):
                yield key[7:]

    def sha1s(self):
        """List the SHA1s."""
        for key in self.db.iterkeys():
            if key.startswith("git\0"):
                yield sha_to_hex(key[4:])


class VersionedFilesContentCache(ContentCache):

    def __init__(self, vf):
        self._vf = vf

    def add(self, obj):
        self._vf.insert_record_stream(
            [versionedfile.ChunkedContentFactory((obj.id,), [], None,
                obj.as_legacy_object_chunks())])

    def __getitem__(self, sha):
        stream = self._vf.get_record_stream([(sha,)], 'unordered', True)
        entry = stream.next() 
        if entry.storage_kind == 'absent':
            raise KeyError(sha)
        return ShaFile._parse_legacy_object(entry.get_bytes_as('fulltext'))


class GitObjectStoreContentCache(ContentCache):

    def __init__(self, store):
        self.store = store

    def add_multi(self, objs):
        self.store.add_objects(objs)

    def add(self, obj, path):
        self.store.add_object(obj)

    def __getitem__(self, sha):
        return self.store[sha]


class IndexCacheUpdater(CacheUpdater):

    def __init__(self, cache, rev):
        self.cache = cache
        self.revid = rev.revision_id
        self.parent_revids = rev.parent_ids
        self._commit = None
        self._entries = []
        self._cache_objs = set()

    def add_object(self, obj, ie, path):
        if obj.type_name == "commit":
            self._commit = obj
            assert type(ie) is dict
            self.cache.idmap._add_git_sha(obj.id, "commit",
                (self.revid, obj.tree, ie))
            self.cache.idmap._add_node(("commit", self.revid, "X"),
                " ".join((obj.id, obj.tree)))
            self._cache_objs.add((obj, path))
        elif obj.type_name == "blob":
            self.cache.idmap._add_git_sha(obj.id, "blob",
                (ie.file_id, ie.revision))
            self.cache.idmap._add_node(("blob", ie.file_id, ie.revision), obj.id)
            if ie.kind == "symlink":
                self._cache_objs.add((obj, path))
        elif obj.type_name == "tree":
            self.cache.idmap._add_git_sha(obj.id, "tree",
                (ie.file_id, self.revid))
            self._cache_objs.add((obj, path))
        else:
            raise AssertionError

    def finish(self):
        self.cache.content_cache.add_multi(self._cache_objs)
        return self._commit


class IndexBzrGitCache(BzrGitCache):

    def __init__(self, transport=None):
        mapper = versionedfile.ConstantMapper("trees")
        shamap = IndexGitShaMap(transport.clone('index'))
        #trees_store = knit.make_file_factory(True, mapper)(transport)
        #content_cache = VersionedFilesContentCache(trees_store)
        from bzrlib.plugins.git.transportgit import TransportObjectStore
        store = TransportObjectStore(transport.clone('objects'))
        content_cache = GitObjectStoreContentCache(store)
        super(IndexBzrGitCache, self).__init__(shamap, content_cache,
                IndexCacheUpdater)


class IndexGitCacheFormat(BzrGitCacheFormat):

    def get_format_string(self):
        return 'bzr-git sha map with git object cache version 1\n'

    def initialize(self, transport):
        super(IndexGitCacheFormat, self).initialize(transport)
        transport.mkdir('index')
        transport.mkdir('objects')
        from bzrlib.plugins.git.transportgit import TransportObjectStore
        TransportObjectStore.init(transport.clone('objects'))

    def open(self, transport):
        return IndexBzrGitCache(transport)


class IndexGitShaMap(GitShaMap):
    """SHA Map that uses the Bazaar APIs to store a cache.

    BTree Index file with the following contents:

    ("git", <sha1>) -> "<type> <type-data1> <type-data2>"
    ("commit", <revid>) -> "<sha1> <tree-id>"
    ("blob", <fileid>, <revid>) -> <sha1>

    """

    def __init__(self, transport=None):
        if transport is None:
            self._transport = None
            self._index = _mod_index.InMemoryGraphIndex(0, key_elements=3)
            self._builder = self._index
        else:
            self._builder = None
            self._transport = transport
            self._index = _mod_index.CombinedGraphIndex([])
            for name in self._transport.list_dir("."):
                if not name.endswith(".rix"):
                    continue
                x = _mod_btree_index.BTreeGraphIndex(self._transport, name,
                    self._transport.stat(name).st_size)
                self._index.insert_index(0, x)

    @classmethod
    def from_repository(cls, repository):
        transport = getattr(repository, "_transport", None)
        if transport is not None:
            try:
                transport.mkdir('git')
            except bzrlib.errors.FileExists:
                pass
            return cls(transport.clone('git'))
        from bzrlib.transport import get_transport
        return cls(get_transport(get_cache_dir()))

    def __repr__(self):
        if self._transport is not None:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)
        else:
            return "%s()" % (self.__class__.__name__)

    def repack(self):
        assert self._builder is None
        self.start_write_group()
        for _, key, value in self._index.iter_all_entries():
            self._builder.add_node(key, value)
        to_remove = []
        for name in self._transport.list_dir('.'):
            if name.endswith('.rix'):
                to_remove.append(name)
        self.commit_write_group()
        del self._index.indices[1:]
        for name in to_remove:
            self._transport.rename(name, name + '.old')

    def start_write_group(self):
        assert self._builder is None
        self._builder = _mod_btree_index.BTreeBuilder(0, key_elements=3)
        self._name = osutils.sha()

    def commit_write_group(self):
        assert self._builder is not None
        stream = self._builder.finish()
        name = self._name.hexdigest() + ".rix"
        size = self._transport.put_file(name, stream)
        index = _mod_btree_index.BTreeGraphIndex(self._transport, name, size)
        self._index.insert_index(0, index)
        self._builder = None
        self._name = None

    def abort_write_group(self):
        assert self._builder is not None
        self._builder = None
        self._name = None

    def _add_node(self, key, value):
        try:
            self._builder.add_node(key, value)
        except bzrlib.errors.BadIndexDuplicateKey:
            # Multiple bzr objects can have the same contents
            return True
        else:
            return False

    def _get_entry(self, key):
        entries = self._index.iter_entries([key])
        try:
            return entries.next()[2]
        except StopIteration:
            if self._builder is None:
                raise KeyError
            entries = self._builder.iter_entries([key])
            try:
                return entries.next()[2]
            except StopIteration:
                raise KeyError

    def _iter_entries_prefix(self, prefix):
        for entry in self._index.iter_entries_prefix([prefix]):
            yield (entry[1], entry[2])
        if self._builder is not None:
            for entry in self._builder.iter_entries_prefix([prefix]):
                yield (entry[1], entry[2])

    def lookup_commit(self, revid):
        return self._get_entry(("commit", revid, "X"))[:40]

    def _add_git_sha(self, hexsha, type, type_data):
        if hexsha is not None:
            self._name.update(hexsha)
            if type == "commit":
                td = (type_data[0], type_data[1])
                try:
                    td += (type_data[2]["testament3-sha1"],)
                except KeyError:
                    pass
            else:
                td = type_data
            self._add_node(("git", hexsha, "X"), " ".join((type,) + td))
        else:
            # This object is not represented in Git - perhaps an empty
            # directory?
            self._name.update(type + " ".join(type_data))

    def lookup_blob_id(self, fileid, revision):
        return self._get_entry(("blob", fileid, revision))

    def lookup_git_sha(self, sha):
        if len(sha) == 20:
            sha = sha_to_hex(sha)
        found = False
        for key, value in self._iter_entries_prefix(("git", sha, None)):
            found = True
            data = value.split(" ", 3)
            if data[0] == "commit":
                if data[3]:
                    verifiers = {"testament3-sha1": data[3]}
                else:
                    verifiers = {}
                yield ("commit", (data[1], data[2], verifiers))
            else:
                yield (data[0], tuple(data[1:]))
        if not found:
            raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        for key, value in self._iter_entries_prefix(("commit", None, None)):
            yield key[1]

    def missing_revisions(self, revids):
        """Return set of all the revisions that are not present."""
        missing_revids = set(revids)
        for _, key, value in self._index.iter_entries((
            ("commit", revid, "X") for revid in revids)):
            missing_revids.remove(key[1])
        return missing_revids

    def sha1s(self):
        """List the SHA1s."""
        for key, value in self._iter_entries_prefix(("git", None, None)):
            yield key[1]


formats = registry.Registry()
formats.register(TdbGitCacheFormat().get_format_string(),
    TdbGitCacheFormat())
formats.register(SqliteGitCacheFormat().get_format_string(),
    SqliteGitCacheFormat())
formats.register(IndexGitCacheFormat().get_format_string(),
    IndexGitCacheFormat())
# In the future, this will become the default:
# formats.register('default', IndexGitCacheFormat())
try:
    import tdb
except ImportError:
    formats.register('default', SqliteGitCacheFormat())
else:
    formats.register('default', TdbGitCacheFormat())



def migrate_ancient_formats(repo_transport):
    # Migrate older cache formats
    repo_transport = remove_readonly_transport_decorator(repo_transport)
    has_sqlite = repo_transport.has("git.db")
    has_tdb = repo_transport.has("git.tdb")
    if not has_sqlite or has_tdb:
        return
    try:
        repo_transport.mkdir("git")
    except bzrlib.errors.FileExists:
        return
    # Prefer migrating git.db over git.tdb, since the latter may not 
    # be openable on some platforms.
    if has_sqlite:
        SqliteGitCacheFormat().initialize(repo_transport.clone("git"))
        repo_transport.rename("git.db", "git/idmap.db")
    elif has_tdb:
        TdbGitCacheFormat().initialize(repo_transport.clone("git"))
        repo_transport.rename("git.tdb", "git/idmap.tdb")


def remove_readonly_transport_decorator(transport):
    if transport.is_readonly():
        return transport._decorated
    return transport


def from_repository(repository):
    """Open a cache file for a repository.

    If the repository is remote and there is no transport available from it
    this will use a local file in the users cache directory
    (typically ~/.cache/bazaar/git/)

    :param repository: A repository object
    """
    repo_transport = getattr(repository, "_transport", None)
    if repo_transport is not None:
        migrate_ancient_formats(repo_transport)
    return BzrGitCacheFormat.from_repository(repository)
