#!/usr/bin/env python
#
#    setup.py -- Install the brz-debian plugin
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of brz-debian.
#
#    brz-debian is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    brz-debian is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with brz-debian; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from info import *

if __name__ == '__main__':

    from distutils.core import setup

    version_string = ".".join([str(v) for v in bzr_plugin_version[:3]])

    setup(name="brz-debian",
          version=version_string,
          description="Build a .deb from a bzr branch",
          author="James Westby",
          author_email="jw+debian@jameswestby.net",
          license = "GNU GPL v2",
          url="http://jameswestby.net/bzr/brz-debian/",
          packages=['breezy.plugins.debian',
                    'breezy.plugins.debian.tests',
                    'breezy.plugins.debian.tests.blackbox',
                    'breezy.plugins.debian.upstream'],
          package_dir={'breezy.plugins.debian': '.'})
