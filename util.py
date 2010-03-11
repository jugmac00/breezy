#    util.py -- Utility functions
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
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

try:
    import hashlib as md5
except ImportError:
    import md5
import signal
import shutil
import tempfile
import os
import re

from bzrlib.trace import mutter

from debian_bundle import deb822
from debian_bundle.changelog import Changelog, ChangelogParseError

from bzrlib import (
        bugtracker,
        errors,
        urlutils,
        version_info as bzr_version_info,
        )
from bzrlib.export import export as bzr_export
from bzrlib.trace import warning
from bzrlib.transport import (
    do_catching_redirections,
    get_transport,
    )
from bzrlib.plugins.builddeb import (
    default_conf,
    local_conf,
    global_conf,
    )
from bzrlib.plugins.builddeb.config import DebBuildConfig
from bzrlib.plugins.builddeb.errors import (
                MissingChangelogError,
                AddChangelogError,
                UnparseableChangelog,
                )


def safe_decode(s):
    """Decode a string into a Unicode value."""
    if isinstance(s, unicode): # Already unicode
        mutter('safe_decode() called on an already-unicode string: %r' % (s,))
        return s
    try:
        return s.decode('utf-8')
    except UnicodeDecodeError, e:
        mutter('safe_decode(%r) falling back to iso-8859-1' % (s,))
        # TODO: Looking at BeautifulSoup it seems to use 'chardet' to try to
        #       guess the encoding of a given text stream. We might want to
        #       take a closer look at that.
        # TODO: Another possibility would be to make the fallback encoding
        #       configurable, possibly exposed as a command-line flag, for now,
        #       this seems 'good enough'.
        return s.decode('iso-8859-1')


def recursive_copy(fromdir, todir):
    """Copy the contents of fromdir to todir.

    Like shutil.copytree, but the destination directory must already exist
    with this method, rather than not exists for shutil.
    """
    mutter("Copying %s to %s", fromdir, todir)
    for entry in os.listdir(fromdir):
        path = os.path.join(fromdir, entry)
        if os.path.isdir(path):
            tosubdir = os.path.join(todir, entry)
            if not os.path.exists(tosubdir):
                os.mkdir(tosubdir)
            recursive_copy(path, tosubdir)
        else:
            shutil.copy(path, todir)


def find_changelog(t, merge, max_blocks=1):
    """Find the changelog in the given tree.

    First looks for 'debian/changelog'. If "merge" is true will also
    look for 'changelog'.

    The returned changelog is created with 'allow_empty_author=True'
    as some people do this but still want to build.
    'max_blocks' defaults to 1 to try and prevent old broken
    changelog entries from causing the command to fail, 

    "larstiq" is a subset of "merge" mode. It indicates that the
    '.bzr' dir is at the same level as 'changelog' etc., rather
    than being at the same level as 'debian/'.

    :param t: the Tree to look in.
    :param merge: whether this is a "merge" package.
    :param max_blocks: Number of max_blocks to parse (defaults to 1)
    :return: (changelog, larstiq) where changelog is the Changelog,
        and larstiq is a boolean indicating whether the file is at
        'changelog' if merge was given, False otherwise.
    """
    changelog_file = 'debian/changelog'
    larstiq = False
    t.lock_read()
    try:
        if not t.has_filename(changelog_file):
            if merge:
                #Assume LarstiQ's layout (.bzr in debian/)
                changelog_file = 'changelog'
                larstiq = True
                if not t.has_filename(changelog_file):
                    raise MissingChangelogError('"debian/changelog" or '
                            '"changelog"')
            else:
                raise MissingChangelogError('"debian/changelog"')
        elif merge and t.has_filename('changelog'):
            # If it is a "larstiq" pacakge and debian is a symlink to
            # "." then it will have found debian/changelog. Try and detect
            # this.
            if (t.kind(t.path2id('debian')) == 'symlink' and 
                t.get_symlink_target(t.path2id('debian')) == '.'):
                changelog_file = 'changelog'
                larstiq = True
        mutter("Using '%s' to get package information", changelog_file)
        changelog_id = t.path2id(changelog_file)
        if changelog_id is None:
            raise AddChangelogError(changelog_file)
        contents = t.get_file_text(changelog_id)
    finally:
       t.unlock()
    changelog = Changelog()
    try:
        changelog.parse_changelog(contents, max_blocks=max_blocks, allow_empty_author=True)
    except ChangelogParseError, e:
        raise UnparseableChangelog(str(e))
    return changelog, larstiq


def strip_changelog_message(changes):
    """Strip a changelog message like debcommit does.

    Takes a list of changes from a changelog entry and applies a transformation
    so the message is well formatted for a commit message.

    :param changes: a list of lines from the changelog entry
    :return: another list of lines with blank lines stripped from the start
        and the spaces the start of the lines split if there is only one logical
        entry.
    """
    if not changes:
        return changes
    while changes and changes[-1] == '':
        changes.pop()
    while changes and changes[0] == '':
        changes.pop(0)

    whitespace_column_re = re.compile(r'  |\t')
    changes = map(lambda line: whitespace_column_re.sub('', line, 1), changes)

    leader_re = re.compile(r'[ \t]*[*+-] ')
    count = len(filter(leader_re.match, changes))
    if count == 1:
        return map(lambda line: leader_re.sub('', line, 1).lstrip(), changes)
    else:
        return changes


def tarball_name(package, version, format=None):
    """Return the name of the .orig.tar.gz for the given package and version.

    :param package: the name of the source package.
    :param version: the upstream version of the package.
    :param format: the format for the tarball. If None then 'gz' will be
         used. You probably want on of 'gz', 'bz2', or 'lzma'.
    :return: a string that is the name of the upstream tarball to use.
    """
    if format is None:
        format = 'gz'
    return "%s_%s.orig.tar.%s" % (package, str(version), format)


def get_snapshot_revision(upstream_version):
    """Return the upstream revision specifier if specified in the upstream version.

    When packaging an upstream snapshot some people use +vcsnn or ~vcsnn to indicate
    what revision number of the upstream VCS was taken for the snapshot. This given
    an upstream version number this function will return an identifier of the
    upstream revision if it appears to be a snapshot. The identifier is a string
    containing a bzr revision spec, so it can be transformed in to a revision.

    :param upstream_version: a string containing the upstream version number.
    :return: a string containing a revision specifier for the revision of the
        upstream branch that the snapshot was taken from, or None if it doesn't
        appear to be a snapshot.
    """
    match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
    if match is not None:
        return match.groups()[0]
    match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
    if match is not None:
        return "svn:%s" % match.groups()[0]
    return None


def get_export_upstream_revision(config, version=None):
    rev = None
    if version is not None:
        rev = get_snapshot_revision(str(version.upstream_version))
    if rev is None:
        rev = config._get_best_opt('export-upstream-revision')
        if rev is not None and version is not None:
            rev = rev.replace('$UPSTREAM_VERSION',
                              str(version.upstream_version))
    return rev


def suite_to_distribution(suite):
    """Infer the distribution from a suite.

    When passed the name of a suite (anything in the distributions field of
    a changelog) it will infer the distribution from that (i.e. Debian or
    Ubuntu).

    :param suite: the string containing the suite
    :return: "debian", "ubuntu", or None if the distribution couldn't be inferred.
    """
    debian_releases = ('woody', 'sarge', 'etch', 'lenny', 'squeeze', 'stable',
            'testing', 'unstable', 'experimental', 'frozen', 'sid')
    debian_targets = ('', '-security', '-proposed-updates', '-backports')
    ubuntu_releases = ('warty', 'hoary', 'breezy', 'dapper', 'edgy',
            'feisty', 'gutsy', 'hardy', 'intrepid', 'jaunty', 'karmic',
            'lucid')
    ubuntu_targets = ('', '-proposed', '-updates', '-security', '-backports')
    all_debian = [r + t for r in debian_releases for t in debian_targets]
    all_ubuntu = [r + t for r in ubuntu_releases for t in ubuntu_targets]
    if suite in all_debian:
        return "debian"
    if suite in all_ubuntu:
        return "ubuntu"
    return None


def lookup_distribution(distribution_or_suite):
    """Get the distribution name based on a distribtion or suite name.

    :param distribution_or_suite: a string that is either the name of
        a distribution or a suite.
    :return: a string with a distribution name or None.
    """
    if distribution_or_suite.lower() in ("debian", "ubuntu"):
        return distribution_or_suite.lower()
    return suite_to_distribution(distribution_or_suite)


def move_file_if_different(source, target, md5sum):
    if os.path.exists(target):
        if os.path.samefile(source, target):
            return
        t_md5sum = md5.md5()
        target_f = open(target)
        try:
            for line in target_f:
                t_md5sum.update(line)
        finally:
            target_f.close()
        if t_md5sum.hexdigest() == md5sum:
            return
    shutil.move(source, target)


def write_if_different(contents, target):
    md5sum = md5.md5()
    md5sum.update(contents)
    fd, temp_path = tempfile.mkstemp("builddeb-rename-")
    fobj = os.fdopen(fd, "wd")
    try:
        try:
            fobj.write(contents)
        finally:
            fobj.close()
        move_file_if_different(temp_path, target, md5sum.hexdigest())
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _download_part(name, base_transport, target_dir, md5sum):
    part_base_dir, part_path = urlutils.split(name)
    f_t = base_transport
    if part_base_dir != '':
        f_t = base_transport.clone(part_base_dir)
    f_f = f_t.get(part_path)
    try:
        target_path = os.path.join(target_dir, part_path)
        fd, temp_path = tempfile.mkstemp(prefix="builldeb-")
        fobj = os.fdopen(fd, "wb")
        try:
            try:
                shutil.copyfileobj(f_f, fobj)
            finally:
                fobj.close()
            move_file_if_different(temp_path, target_path, md5sum)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    finally:
        f_f.close()


def open_file(path):
    filename, transport = open_transport(path)
    return open_file_via_transport(filename, transport)


def open_transport(path):
  """Obtain an appropriate transport instance for the given path."""
  base_dir, path = urlutils.split(path)
  transport = get_transport(base_dir)
  return (path, transport)


def open_file_via_transport(filename, transport):
  """Open a file using the transport, follow redirects as necessary."""
  def open_file(transport):
    return transport.get(filename)
  def follow_redirection(transport, e, redirection_notice):
    mutter(redirection_notice)
    _filename, redirected_transport = open_transport(e.target)
    return redirected_transport

  result = do_catching_redirections(open_file, transport, follow_redirection)
  return result


def _dget(cls, dsc_location, target_dir):
    if not os.path.isdir(target_dir):
        raise errors.NotADirectory(target_dir)
    path, dsc_t = open_transport(dsc_location)
    dsc_contents = open_file_via_transport(path, dsc_t).read()
    dsc = cls(dsc_contents)
    for file_details in dsc['files']:
        name = file_details['name']
        _download_part(name, dsc_t, target_dir, file_details['md5sum'])
    target_file = os.path.join(target_dir, path)
    write_if_different(dsc_contents, target_file)
    return target_file


def dget(dsc_location, target_dir):
    return _dget(deb822.Dsc, dsc_location, target_dir)


def dget_changes(changes_location, target_dir):
    return _dget(deb822.Changes, changes_location, target_dir)


def get_parent_dir(target):
    parent = os.path.dirname(target)
    if os.path.basename(target) == '':
        parent = os.path.dirname(parent)
    return parent


def find_bugs_fixed(changes, branch, _lplib=None):
    if _lplib is None:
        from bzrlib.plugins.builddeb import launchpad as _lplib
    bugs = []
    for change in changes:
        for match in re.finditer("closes:\s*(?:bug)?\#?\s?\d+"
                "(?:,\s*(?:bug)?\#?\s?\d+)*", change,
                re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\d+", closes_list):
                bug_url = bugtracker.get_bug_url("deb", branch,
                        match.group(0))
                bugs.append(bug_url + " fixed")
                lp_bugs = _lplib.ubuntu_bugs_for_debian_bug(match.group(0))
                if len(lp_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("lp", branch,
                            lp_bugs[0])
                    bugs.append(bug_url + " fixed")
        for match in re.finditer("lp:\s+\#\d+(?:,\s*\#\d+)*",
                change, re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\d+", closes_list):
                bug_url = bugtracker.get_bug_url("lp", branch,
                        match.group(0))
                bugs.append(bug_url + " fixed")
                deb_bugs = _lplib.debian_bugs_for_ubuntu_bug(match.group(0))
                if len(deb_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("deb", branch,
                            deb_bugs[0])
                    bugs.append(bug_url + " fixed")
    return bugs


def find_extra_authors(changes):
    extra_author_re = re.compile(r"\s*\[([^\]]+)]\s*")
    authors = []
    for change in changes:
        # Parse out any extra authors.
        match = extra_author_re.match(change)
        if match is not None:
            new_author = safe_decode(match.group(1).strip())
            already_included = False
            for author in authors:
                if author.startswith(new_author):
                    already_included = True
                    break
            if not already_included:
                authors.append(new_author)
    return authors


def find_thanks(changes):
    thanks_re = re.compile(r"[tT]hank(?:(?:s)|(?:you))(?:\s*to)?"
            "((?:\s+(?:(?:\w\.)|(?:\w+(?:-\w+)*)))+"
            "(?:\s+<[^@>]+@[^@>]+>)?)",
            re.UNICODE)
    thanks = []
    changes_str = safe_decode(" ".join(changes))
    for match in thanks_re.finditer(changes_str):
        if thanks is None:
            thanks = []
        thanks_str = match.group(1).strip()
        thanks_str = re.sub(r"\s+", " ", thanks_str)
        thanks.append(thanks_str)
    return thanks


def get_commit_info_from_changelog(changelog, branch, _lplib=None):
    """Retrieves the messages from the last section of debian/changelog.

    Reads the latest stanza of debian/changelog and returns the
    text of the changes in that section. It also returns other
    information about the change, including the authors of the change,
    anyone that is thanked, and the bugs that are declared fixed by it.

    :return: a tuple (message, authors, thanks, bugs). message is the
        commit message that should be used. authors is a list of strings,
        with those that contributed to the change, thanks is a list
        of string, with those who were thanked in the changelog entry.
        bugs is a list of bug URLs like for --fixes.
        If the information is not available then any can be None.
    """
    message = None
    authors = []
    thanks = []
    bugs = []
    if changelog._blocks:
        block = changelog._blocks[0]
        authors = [safe_decode(block.author)]
        changes = strip_changelog_message(block.changes())
        authors += find_extra_authors(changes)
        bugs = find_bugs_fixed(changes, branch, _lplib=_lplib)
        thanks = find_thanks(changes)
        message = safe_decode("\n".join(changes).replace("\r", ""))
    return (message, authors, thanks, bugs)


def find_last_distribution(changelog):
    """Find the last changelog that was used in a changelog.

    This will skip stanzas with the 'UNRELEASED' distribution.
    
    :param changelog: Changelog to analyze
    """
    for block in changelog._blocks:
        distribution = block.distributions.split(" ")[0]
        if distribution != "UNRELEASED":
            return distribution
    return None


def subprocess_setup():
    # Python installs a SIGPIPE handler by default. This is usually not what
    # non-Python subprocesses expect.
    # Many, many thanks to Colin Watson
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def debuild_config(tree, working_tree, no_user_config):
    """Obtain the Debuild configuration object.

    :param tree: A Tree object, can be a WorkingTree or RevisionTree.
    :param working_tree: Whether the tree is a working tree.
    :param no_user_config: Whether to skip the user configuration
    """
    config_files = []
    user_config = None
    if (working_tree and tree.has_filename(local_conf)):
        if tree.path2id(local_conf) is None:
            config_files.append((tree.get_file_byname(local_conf), True,
                        "local.conf"))
        else:
            warning('Not using configuration from %s as it is versioned.')
    if not no_user_config:
        config_files.append((global_conf, True))
        user_config = global_conf
    if tree.path2id(default_conf):
        config_files.append((tree.get_file(tree.path2id(default_conf)), False,
                    "default.conf"))
    config = DebBuildConfig(config_files, tree=tree)
    config.set_user_config(user_config)
    return config


def export(tree, dest, format=None, root=None, subdir=None, filtered=False):
    """Simple wrapper around bzrlib.export.export that prefers 
    per_file_timestamps if it is supported.

    """
    # per_file_timestamps is available as of bzr 2.2.0
    if bzr_version_info > (2, 2, 0):
        return bzr_export(tree, dest, format=format, root=root, subdir=subdir,
            filtered=filtered, per_file_timestamps=True)
    else:
        return bzr_export(tree, dest, format=format, root=root, subdir=subdir,
            filtered=filtered, per_file_timestamps=True)
