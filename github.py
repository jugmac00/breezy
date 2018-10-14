# Copyright (C) 2018 Breezy Developers
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Support for GitHub."""

from __future__ import absolute_import

from .propose import (
    Hoster,
    MergeProposal,
    MergeProposalBuilder,
    MergeProposalExists,
    NoMergeProposal,
    UnsupportedHoster,
    )

from ... import (
    branch as _mod_branch,
    controldir,
    errors,
    hooks,
    urlutils,
    version_string as breezy_version,
    )
from ...config import AuthenticationConfig, GlobalStack
from ...git.urls import git_url_to_bzr_url
from ...i18n import gettext
from ...sixish import PY3
from ...trace import note
from ...lazy_import import lazy_import
lazy_import(globals(), """
from github import Github
""")


class NotGitHubUrl(errors.BzrError):

    _fmt = "Not a GitHub URL: %(url)s"

    def __init__(self, url):
        errors.BzrError.__init__(self)
        self.url = url


def connect_github():
    user_agent = user_agent="Breezy/%s" % breezy_version

    auth = AuthenticationConfig()

    credentials = auth.get_credentials('https', 'github.com')
    if credentials is not None:
        return Github(credentials['user'], credentials['password'],
                      user_agent=user_agent)

    # TODO(jelmer): Support using an access token
    #return Github("token", user_agent=user_agent)
    return Github(user_agent=user_agent)


def parse_github_url(branch):
    url = urlutils.split_segment_parameters(branch.user_url)[0]
    (scheme, user, password, host, port, path) = urlutils.parse_url(
        url)
    if host != 'github.com':
        raise NotGitHubUrl(url)
    (owner, repo_name) = path.strip('/').split('/')
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    return owner, repo_name, branch.name


def github_url_to_bzr_url(url, branch_name):
    if not PY3:
        branch_name = branch_name.encode('utf-8')
    return urlutils.join_segment_parameters(
            git_url_to_bzr_url(url), {"branch": branch_name})


class GitHub(Hoster):

    supports_merge_proposal_labels = True

    def __repr__(self):
        return "GitHub()"

    def __init__(self):
        self.gh = connect_github()

    def publish_derived(self, local_branch, base_branch, name, project=None,
                        owner=None, revision_id=None, overwrite=False):
        import github
        base_owner, base_project, base_branch_name = parse_github_url(base_branch)
        base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
        if owner is None:
            owner = self.gh.get_user().login
        if project is None:
            project = base_repo.name
        try:
            remote_repo = self.gh.get_repo('%s/%s' % (owner, project))
            remote_repo.id
        except github.UnknownObjectException:
            base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
            if owner == self.gh.get_user().login:
                owner_obj = self.gh.get_user()
            else:
                owner_obj = self.gh.get_organization(owner)
            remote_repo = owner_obj.create_fork(base_repo)
            note(gettext('Forking new repository %s from %s') %
                    (remote_repo.html_url, base_repo.html_url))
        else:
            note(gettext('Reusing existing repository %s') % remote_repo.html_url)
        remote_dir = controldir.ControlDir.open(git_url_to_bzr_url(remote_repo.ssh_url))
        push_result = remote_dir.push_branch(local_branch, revision_id=revision_id,
            overwrite=overwrite, name=name)
        return push_result.target_branch, github_url_to_bzr_url(
                remote_repo.html_url, name)

    def get_push_url(self, branch):
        owner, project, branch_name = parse_github_url(branch)
        repo = self.gh.get_repo('%s/%s' % (owner, project))
        return github_url_to_bzr_url(repo.ssh_url, branch_name)

    def get_derived_branch(self, base_branch, name, project=None, owner=None):
        import github
        base_owner, base_project, base_branch_name = parse_github_url(base_branch)
        base_repo = self.gh.get_repo('%s/%s' % (base_owner, base_project))
        if owner is None:
            owner = self.gh.get_user().login
        if project is None:
            project = base_repo.name
        try:
            remote_repo = self.gh.get_repo('%s/%s' % (owner, project))
            full_url = github_url_to_bzr_url(remote_repo.ssh_url, name)
            return _mod_branch.Branch.open(full_url)
        except github.UnknownObjectException:
            raise errors.NotBranchError('https://github.com/%s/%s' % (owner, project))

    def get_proposer(self, source_branch, target_branch):
        return GitHubMergeProposalBuilder(self.gh, source_branch, target_branch)

    def get_proposal(self, source_branch, target_branch):
        (source_owner, source_repo_name, source_branch_name) = (
                parse_github_url(source_branch))
        (target_owner, target_repo_name, target_branch_name) = (
                parse_github_url(target_branch))
        target_repo = self.gh.get_repo("%s/%s" % (target_owner, target_repo_name))
        for pull in target_repo.get_pulls(head=target_branch_name):
            if pull.head.ref != source_branch_name:
                continue
            if (pull.head.repo.owner.login != source_owner or
                pull.head.repo.name != source_repo_name):
                continue
            return MergeProposal(pull.html_url)
        raise NoMergeProposal()

    def hosts(self, branch):
        try:
            parse_github_url(branch)
        except NotGitHubUrl:
            return False
        else:
            return True

    @classmethod
    def probe(cls, branch):
        try:
            parse_github_url(branch)
        except NotGitHubUrl:
            raise UnsupportedHoster(branch)
        return cls()


class GitHubMergeProposalBuilder(MergeProposalBuilder):

    def __init__(self, gh, source_branch, target_branch):
        self.gh = gh
        self.source_branch = source_branch
        self.target_branch = target_branch
        (self.target_owner, self.target_repo_name, self.target_branch_name) = (
                parse_github_url(self.target_branch))
        (self.source_owner, self.source_repo_name, self.source_branch_name) = (
                parse_github_url(self.source_branch))

    def get_infotext(self):
        """Determine the initial comment for the merge proposal."""
        info = []
        info.append("Merge %s into %s:%s\n" % (
            self.source_branch_name, self.target_owner,
            self.target_branch_name))
        info.append("Source: %s\n" % self.source_branch.user_url)
        info.append("Target: %s\n" % self.target_branch.user_url)
        return ''.join(info)

    def get_initial_body(self):
        """Get a body for the proposal for the user to modify.

        :return: a str or None.
        """
        return None

    def create_proposal(self, description, reviewers=None, labels=None):
        """Perform the submission."""
        import github
        # TODO(jelmer): Probe for right repo name
        if self.target_repo_name.endswith('.git'):
            self.target_repo_name = self.target_repo_name[:-4]
        target_repo = self.gh.get_repo("%s/%s" % (self.target_owner, self.target_repo_name))
        # TODO(jelmer): Allow setting title explicitly?
        title = description.splitlines()[0]
        # TOOD(jelmer): Set maintainers_can_modify?
        try:
            pull_request = target_repo.create_pull(
                title=title, body=description,
                head="%s:%s" % (self.source_owner, self.source_branch_name),
                base=self.target_branch_name)
        except github.GithubException as e:
            if e.status == 422:
                raise MergeProposalExists(self.source_branch.user_url)
            raise
        if reviewers:
            for reviewer in reviewers:
                pull_request.assignees.append(
                    self.gh.get_user(reviewer))
        if labels:
            for label in labels:
                pull_request.issue.labels.append(label)
        return MergeProposal(pull_request.html_url)
