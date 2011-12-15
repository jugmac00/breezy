bzr_plugin_name = "git"

dulwich_minimum_version = (0, 8, 1)

# versions ending in 'exp' mean experimental mappings
# versions ending in 'dev' mean development version
# versions ending in 'final' mean release (well tested, etc)
bzr_plugin_version = (0, 6, 6, 'final', 0)

bzr_commands = ["git-import", "git-object", "git-refs", "git-apply"]

bzr_compatible_versions = [(2, x, 0) for x in [4]]

bzr_minimum_version = bzr_compatible_versions[0]

bzr_maximum_version = bzr_compatible_versions[-1]

bzr_control_formats = {"Git":{'.git/': None}}
