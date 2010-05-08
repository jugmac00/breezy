# Copyright (C) 2010 by Canonical Ltd
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

from bzrlib.tests import TestCase, TestCaseWithTransport, Feature
from bzrlib import commands
from ..bashcomp import *
import bzrlib
import os
import subprocess


class _ExecutableFeature(Feature):
    """Feature testing whether an executable of a given name is on the PATH."""

    bash_paths = ['/bin/bash', '/usr/bin/bash']

    def __init__(self, name):
        super(_ExecutableFeature, self).__init__()
        self.name = name

    @property
    def path(self):
        try:
            return self._path
        except AttributeError:
            self._path = self._get_path()
            return self._path

    def _get_path(self):
        path = os.environ.get('PATH')
        if path is None:
            return None
        for d in path.split(os.pathsep):
            f = os.path.join(d, self.name)
            if os.access(f, os.X_OK):
                return f
        return None

    def available(self):
        return self.path is not None

    def feature_name(self):
        return '%s executable' % self.name

BashFeature = _ExecutableFeature('bash')
SedFeature = _ExecutableFeature('sed')


class BashCompletionMixin(object):
    """Component for testing execution of a bash completion script."""

    _test_needs_features = [BashFeature]

    def complete(self, words, cword=-1):
        """Perform a bash completion.

        :param words: a list of words representing the current command.
        :param cword: the current word to complete, defaults to the last one.
        """
        if self.script is None:
            self.script = self.get_script()
        proc = subprocess.Popen([BashFeature.path, '--noprofile'],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        if cword < 0:
            cword = len(words) + cword
        input = '%s\n' % self.script
        input += ('COMP_WORDS=( %s )\n' %
                  ' '.join(["'"+w.replace("'", "'\\''")+"'" for w in words]))
        input += 'COMP_CWORD=%d\n' % cword
        input += '%s\n' % getattr(self, 'script_name', '_bzr')
        input += 'echo ${#COMPREPLY[*]}\n'
        input += "IFS=$'\\n'\n"
        input += 'echo "${COMPREPLY[*]}"\n'
        (out, err) = proc.communicate(input)
        if '' != err:
            raise AssertionError('Unexpected error message:\n%s' % err)
        self.assertEqual('', err, 'No messages to standard error')
        #import sys
        #print >>sys.stdout, '---\n%s\n---\n%s\n---\n' % (input, out)
        lines = out.split('\n')
        nlines = int(lines[0])
        del lines[0]
        self.assertEqual('', lines[-1], 'Newline at end')
        del lines[-1]
        if nlines == 0 and len(lines) == 1 and lines[0] == '':
            del lines[0]
        self.assertEqual(nlines, len(lines), 'No newlines in generated words')
        self.completion_result = set(lines)
        return self.completion_result

    def assertCompletionEquals(self, *words):
        self.assertEqual(set(words), self.completion_result)

    def assertCompletionContains(self, *words):
        missing = set(words) - self.completion_result
        if missing:
            raise AssertionError('Completion should contain %r but it has %r'
                                 % (missing, self.completion_result))

    def assertCompletionOmits(self, *words):
        surplus = set(words) & self.completion_result
        if surplus:
            raise AssertionError('Completion should omit %r but it has %r'
                                 % (surplus, res, self.completion_result))

    def get_script(self):
        commands.install_bzr_command_hooks()
        dc = DataCollector()
        data = dc.collect()
        cg = BashCodeGen(data)
        res = cg.function()
        return res


class TestBashCompletion(TestCase, BashCompletionMixin):
    """Test bash completions that don't execute bzr."""

    def __init__(self, methodName='testMethod'):
        super(TestBashCompletion, self).__init__(methodName)
        self.script = None

    def test_simple_scipt(self):
        """Ensure that the test harness works as expected"""
        self.script = """
_bzr() {
    COMPREPLY=()
    # add all words in reverse order, with some markup around them
    for ((i = ${#COMP_WORDS[@]}; i > 0; --i)); do
        COMPREPLY+=( "-${COMP_WORDS[i-1]}+" )
    done
    # and append the current word
    COMPREPLY+=( "+${COMP_WORDS[COMP_CWORD]}-" )
}
"""
        self.complete(['foo', '"bar', "'baz"], cword=1)
        self.assertCompletionEquals("-'baz+", '-"bar+', '-foo+', '+"bar-')

    def test_cmd_ini(self):
        self.complete(['bzr', 'ini'])
        self.assertCompletionContains('init', 'init-repo', 'init-repository')
        self.assertCompletionOmits('commit')

    def test_init_opts(self):
        self.complete(['bzr', 'init', '-'])
        self.assertCompletionContains('-h', '--2a', '--format=2a')

    def test_global_opts(self):
        self.complete(['bzr', '-', 'init'], cword=1)
        self.assertCompletionContains('--no-plugins', '--builtin')

    def test_commit_dashm(self):
        self.complete(['bzr', 'commit', '-m'])
        self.assertCompletionEquals('-m')

    def test_status_negated(self):
        self.complete(['bzr', 'status', '--n'])
        self.assertCompletionContains('--no-versioned', '--no-verbose')

    def test_init_format_any(self):
        self.complete(['bzr', 'init', '--format', '=', 'directory'], cword=3)
        self.assertCompletionContains('1.9', '2a')

    def test_init_format_2(self):
        self.complete(['bzr', 'init', '--format', '=', '2', 'directory'],
                      cword=4)
        self.assertCompletionContains('2a')
        self.assertCompletionOmits('1.9')


class TestBashCompletionInvoking(TestCaseWithTransport, BashCompletionMixin):
    """Test bash completions that might execute bzr.

    Only the syntax ``$(bzr ...`` is supported so far. The bzr command
    will be replaced by the bzr instance running this selftest.
    """

    def __init__(self, methodName='testMethod'):
        super(TestBashCompletionInvoking, self).__init__(methodName)
        self.script = None

    def get_script(self):
        s = super(TestBashCompletionInvoking, self).get_script()
        return s.replace("$(bzr ", "$('%s' " % self.get_bzr_path())

    def test_revspec_tag_all(self):
        self.requireFeature(SedFeature)
        wt = self.make_branch_and_tree('.', format='dirstate-tags')
        wt.branch.tags.set_tag('tag1', 'null:')
        wt.branch.tags.set_tag('tag2', 'null:')
        wt.branch.tags.set_tag('3tag', 'null:')
        self.complete(['bzr', 'log', '-r', 'tag', ':'])
        self.assertCompletionEquals('tag1', 'tag2', '3tag')

    def test_revspec_tag_prefix(self):
        self.requireFeature(SedFeature)
        wt = self.make_branch_and_tree('.', format='dirstate-tags')
        wt.branch.tags.set_tag('tag1', 'null:')
        wt.branch.tags.set_tag('tag2', 'null:')
        wt.branch.tags.set_tag('3tag', 'null:')
        self.complete(['bzr', 'log', '-r', 'tag', ':', 't'])
        self.assertCompletionEquals('tag1', 'tag2')

    def test_revspec_tag_spaces(self):
        self.requireFeature(SedFeature)
        wt = self.make_branch_and_tree('.', format='dirstate-tags')
        wt.branch.tags.set_tag('tag with spaces', 'null:')
        self.complete(['bzr', 'log', '-r', 'tag', ':', 't'])
        self.assertCompletionEquals(r'tag\ with\ spaces')
        self.complete(['bzr', 'log', '-r', '"tag:t'])
        self.assertCompletionEquals('tag:tag with spaces')
        self.complete(['bzr', 'log', '-r', "'tag:t"])
        self.assertCompletionEquals('tag:tag with spaces')

    def test_revspec_tag_endrange(self):
        self.requireFeature(SedFeature)
        wt = self.make_branch_and_tree('.', format='dirstate-tags')
        wt.branch.tags.set_tag('tag1', 'null:')
        wt.branch.tags.set_tag('tag2', 'null:')
        self.complete(['bzr', 'log', '-r', '3..tag', ':', 't'])
        self.assertCompletionEquals('tag1', 'tag2')
        self.complete(['bzr', 'log', '-r', '"3..tag:t'])
        self.assertCompletionEquals('3..tag:tag1', '3..tag:tag2')
        self.complete(['bzr', 'log', '-r', "'3..tag:t"])
        self.assertCompletionEquals('3..tag:tag1', '3..tag:tag2')


class TestBashCodeGen(TestCase):

    def test_command_names(self):
        data = CompletionData()
        bar = CommandData('bar')
        bar.aliases.append('baz')
        data.commands.append(bar)
        data.commands.append(CommandData('foo'))
        cg = BashCodeGen(data)
        self.assertEqual('bar baz foo', cg.command_names())

    def test_debug_output(self):
        data = CompletionData()
        self.assertEqual('', BashCodeGen(data, debug=False).debug_output())
        self.assertTrue(BashCodeGen(data, debug=True).debug_output())

    def test_bzr_version(self):
        data = CompletionData()
        cg = BashCodeGen(data)
        self.assertEqual('%s.' % bzrlib.version_string, cg.bzr_version())
        data.plugins['foo'] = PluginData('foo', '1.0')
        data.plugins['bar'] = PluginData('bar', '2.0')
        cg = BashCodeGen(data)
        self.assertEqual('''\
%s and the following plugins:
# bar 2.0
# foo 1.0''' % bzrlib.version_string, cg.bzr_version())

    def test_global_options(self):
        data = CompletionData()
        data.global_options.add('--foo')
        data.global_options.add('--bar')
        cg = BashCodeGen(data)
        self.assertEqual('--bar --foo', cg.global_options())

    def test_command_cases(self):
        data = CompletionData()
        bar = CommandData('bar')
        bar.aliases.append('baz')
        bar.options.append(OptionData('--opt'))
        data.commands.append(bar)
        data.commands.append(CommandData('foo'))
        cg = BashCodeGen(data)
        self.assertEqualDiff('''\
\tbar|baz)
\t\tcmdOpts=( --opt )
\t\t;;
\tfoo)
\t\tcmdOpts=(  )
\t\t;;
''', cg.command_cases())

    def test_command_case(self):
        cmd = CommandData('cmd')
        cmd.plugin = PluginData('plugger', '1.0')
        bar = OptionData('--bar')
        bar.registry_keys = ['that', 'this']
        bar.error_messages.append('Some error message')
        cmd.options.append(bar)
        cmd.options.append(OptionData('--foo'))
        data = CompletionData()
        data.commands.append(cmd)
        cg = BashCodeGen(data)
        self.assertEqualDiff('''\
\tcmd)
\t\t# plugin "plugger 1.0"
\t\t# Some error message
\t\tcmdOpts=( --bar=that --bar=this --foo )
\t\tcase $curOpt in
\t\t\t--bar) optEnums=( that this ) ;;
\t\tesac
\t\t;;
''', cg.command_case(cmd))


class TestDataCollector(TestCase):

    def setUp(self):
        super(TestDataCollector, self).setUp()
        commands.install_bzr_command_hooks()

    def test_global_options(self):
        dc = DataCollector()
        dc.global_options()
        self.assertSubset(['--no-plugins', '--builtin'],
                           dc.data.global_options)

    def test_commands(self):
        dc = DataCollector()
        dc.commands()
        self.assertSubset(['init', 'init-repo', 'init-repository'],
                           dc.data.all_command_aliases())

    def test_commands_from_plugins(self):
        dc = DataCollector()
        dc.commands()
        self.assertSubset(['bash-completion'],
                           dc.data.all_command_aliases())

    def test_commit_dashm(self):
        dc = DataCollector()
        cmd = dc.command('commit')
        self.assertSubset(['-m'],
                           [str(o) for o in cmd.options])

    def test_status_negated(self):
        dc = DataCollector()
        cmd = dc.command('status')
        self.assertSubset(['--no-versioned', '--no-verbose'],
                           [str(o) for o in cmd.options])

    def test_init_format(self):
        dc = DataCollector()
        cmd = dc.command('init')
        for opt in cmd.options:
            if opt.name == '--format':
                self.assertSubset(['2a'], opt.registry_keys)
                return
        raise AssertionError('Option --format not found')
