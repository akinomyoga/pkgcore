# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

"""
restriction related utilities
"""

from pkgcore.util.lists import iter_flatten
from pkgcore.util.containers import InvertedContains
from pkgcore.restrictions import packages, boolean

def _is_package_instance(inst):
	return getattr(inst, "type", None) == packages.package_type and not isinstance(inst, boolean.base)

def collect_package_restrictions(restrict, attrs=None):
	"""walks a restriction, descending as neccessary and returning any PackageRestrictions that work
	on attrs passed in

	@param restrict: package instance to scan
	@param attrs: None (return all package restrictions), or a sequence of specific attrs the package restriction
	must work against
	"""
	if attrs is None:
		attrs = InvertedContains()
	elif isinstance(attrs, (list, tuple)):
		attrs = frozenset(attrs)
	return (r for r in iter_flatten(restrict, skip_func=_is_package_instance) 
		if getattr(r, "attr", None) in attrs)
