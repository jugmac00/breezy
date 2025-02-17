##############################################################################
#
# Copyright (c) 2006 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Bootstrap a buildout-based project

Simply run this script in a directory containing a buildout.cfg.
The script accepts buildout command-line options, so you can
use the -c option to specify an alternate configuration file.

$Id: bootstrap.py 90478 2008-08-27 22:44:46Z georgyberdyshev $
"""

import os, shutil, sys, tempfile, urllib2

tmpeggs = tempfile.mkdtemp()

is_jython = sys.platform.startswith('java')

try:
    import pkg_resources
except ModuleNotFoundError:
    ez = {}
    exec(urllib2.urlopen('http://peak.telecommunity.com/dist/ez_setup.py'
                         ).read(), ez)
    ez['use_setuptools'](to_dir=tmpeggs, download_delay=0)

    import pkg_resources

if sys.platform == 'win32':
    def quote(c):
        if ' ' in c:
            return '"%s"' % c # work around spawn lamosity on windows
        else:
            return c
else:
    def quote(c):
        return c

cmd = 'from setuptools.command.easy_install import main; main()'
ws = pkg_resources.working_set
env = dict(
    os.environ,
    PYTHONPATH=ws.find(pkg_resources.Requirement.parse('setuptools')).location)

if is_jython:
    import subprocess

    assert subprocess.Popen(
        [sys.executable] +
        ['-c', quote(cmd), '-mqNxd', quote(tmpeggs), 'zc.buildout'],
        env=env,).wait() == 0

else:
    assert os.spawnle(
        os.P_WAIT, sys.executable, quote(sys.executable),
        '-c', quote(cmd), '-mqNxd', quote(tmpeggs), 'zc.buildout', env,
        ) == 0

ws.add_entry(tmpeggs)
ws.require('zc.buildout')
import zc.buildout.buildout
zc.buildout.buildout.main(sys.argv[1:] + ['bootstrap'])
shutil.rmtree(tmpeggs)
