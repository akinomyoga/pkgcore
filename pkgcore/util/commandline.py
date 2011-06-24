# Copyright: 2009-2011 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2


"""Utilities for writing commandline utilities.

pkgcore scripts should use the L{OptionParser} subclass here for a
consistent commandline "look and feel" (and it tries to make life a
bit easier too). They will probably want to use L{main} from an C{if
__name__ == '__main__'} block too: it will take care of things like
consistent exception handling.

See dev-notes/commandline.rst for more complete documentation.
"""

__all__ = ("FormattingHandler", "Values", "Option", "OptionParser",
    "MySystemExit", "main",
)

import sys
import os.path
import logging

from pkgcore.config import load_config, errors
from snakeoil import formatters, demandload, currying
import optparse
from pkgcore.util import argparse
from pkgcore.util.commandline_optparse import *

demandload.demandload(globals(),
    'snakeoil.fileutils:iter_read_bash',
    'snakeoil:osutils',
    'pkgcore:version',
    'pkgcore.config:basics',
    'pkgcore.restrictions:packages',
    'pkgcore.util:parserestrict',
    'pkgcore.ebuild:atom',
)


class FormattingHandler(logging.Handler):

    """Logging handler printing through a formatter."""

    def __init__(self, formatter):
        logging.Handler.__init__(self)
        # "formatter" clashes with a Handler attribute.
        self.out = formatter

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            color = 'red'
        elif record.levelno >= logging.WARNING:
            color = 'yellow'
        else:
            color = 'cyan'
        first_prefix = (self.out.fg(color), self.out.bold, record.levelname,
                        self.out.reset, ' ', record.name, ': ')
        later_prefix = (len(record.levelname) + len(record.name)) * ' ' + ' : '
        self.out.first_prefix.extend(first_prefix)
        self.out.later_prefix.append(later_prefix)
        try:
            for line in self.format(record).split('\n'):
                self.out.write(line, wrap=True)
        finally:
            self.out.later_prefix.pop()
            for i in xrange(len(first_prefix)):
                self.out.first_prefix.pop()


def string_bool(value):
    value = value.lower()
    if value in ('y', 'yes', 'true'):
        return True
    elif value in ('n', 'no', 'false'):
        return False
    raise ValueError(value)


class StoreBool(argparse._StoreAction):
    def __init__(self,
                option_strings,
                dest,
                const=None,
                default=None,
                required=False,
                help=None,
                metavar='BOOLEAN'):
        super(StoreBool, self).__init__(
            option_strings=option_strings,
            dest=dest,
            const=const,
            default=default,
            type=self.convert_bool,
            required=required,
            help=help,
            metavar=metavar)

    @staticmethod
    def convert_bool(value):
        value = value.lower()
        if value in ('y', 'yes', 'true'):
            return True
        elif value in ('n', 'no', 'false'):
            return False
        raise ValueError("value %r must be [y|yes|true|n|no|false]" % (value,))


class StoreConfig(argparse._StoreAction):
    def __init__(self,
                option_strings,
                dest,
                nargs=None,
                const=None,
                default=None,
                config_type=None,
                required=False,
                help=None,
                metavar=None):

        if type is None:
            raise ValueError("type must specify the config type to load")

        super(StoreConfig, self).__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=nargs,
            const=const,
            default=default,
            type=str,
            required=required,
            help=help)
        self.config_type = config_type

    def _get_kwargs(self):
        names = [
            'option_strings',
            'dest',
            'nargs',
            'const',
            'default',
            'config_type',
            'choices',
            'help',
            'metavar',
        ]
        return [(name, getattr(self, name)) for name in names]

    def _load_obj(self, sections, name):
        try:
            return sections[name]
        except KeyError:
            raise argparse.ArgumentError(self, "couldn't find %s %r" %
                (self.config_type, name))

    def __call__(self, parser, namespace, values, option_string=None):
        config = getattr(namespace, 'config', None)
        if config is None:
            raise ValueError("no config found.  Internal bug")
        sections = getattr(config, self.config_type)
        if isinstance(values, basestring):
            value = self._load_obj(sections, values)
        else:
            value = [self._load_obj(sections, x) for x in values]
        setattr(namespace, self.dest, value)


class Delayed(argparse.Action):

    def __init__(self, option_strings, dest, target=None, priority=0, **kwds):
        if target is None:
            raise ValueError("target must be non None for Delayed")

        self.priority = int(priority)
        self.target = target(option_strings=option_strings, dest=dest, **kwds.copy())
        super(Delayed, self).__init__(option_strings=option_strings[:],
            dest=dest, nargs=kwds.get("nargs", None), required=kwds.get("required", None),
            help=kwds.get("help", None), metavar=kwds.get("metavar", None))

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, DelayedValue(
            currying.partial(self.target, parser, namespace, values, option_string),
            priority=self.priority))


class DelayedValue(object):

    def __init__(self, invokable, priority, delayed_parse=True):
        self.invokable = invokable
        self.delayed_parse = delayed_parse
        self.priority = priority

    def __call__(self, namespace, attr):
        if self.delayed_parse:
            self.invokable()
        else:
            self.invokable(namespace, attr)


class ArgumentParser(argparse.ArgumentParser):

    def __init__(self,
                 prog=None,
                 usage=None,
                 description=None,
                 epilog=None,
                 version=None,
                 parents=[],
                 formatter_class=argparse.HelpFormatter,
                 prefix_chars='-',
                 fromfile_prefix_chars=None,
                 argument_default=None,
                 conflict_handler='error',
                 add_help=True):
        super(ArgumentParser, self).__init__(prog=prog, usage=usage,
            description=description, epilog=epilog, version=version,
            parents=parents, formatter_class=formatter_class,
            prefix_chars=prefix_chars, fromfile_prefix_chars=fromfile_prefix_chars,
            argument_default=argument_default, conflict_handler=conflict_handler,
            add_help=add_help)

    def parse_args(self, args=None, namespace=None):
        args = argparse.ArgumentParser.parse_args(self, args, namespace)

        # bleh.  direct access...
        i = ((attr, val) for attr, val in args.__dict__.iteritems()
            if isinstance(val, DelayedValue))
        for attr, delayed in sorted(i, key=lambda val:val[1].priority):
            delayed(args, attr)
        return args

    @staticmethod
    def _delayed_default_target(target, key, parser, values, option_string):
        target(values, key)

def store_config(values, key):
    setattr(values, key, load_config())

def mk_argparser(config=True, domain=True, color=True, debug=True, **kwds):
    p = ArgumentParser(**kwds)
    if debug:
        p.add_argument('--debug', action='store_true', help="Enable debugging checks")
    if color:
        p.add_argument('--color', action=StoreBool,
            help="Enable or disable color support.")

    if config:
        p.add_argument('--config-modify', '--add-config', '--new-config', nargs=3,
            metavar="SECTION KEY VALUE",
            help="Modify configuration section, creating it if needed.  Takes three "
                "arguments- the name of the section to modify, the key, and the "
                "value.")
        p.add_argument('--config-empty', '--empty-config', action='store_true',
            help="Do not load user/system configuration.")

        p.set_defaults(config=DelayedValue(store_config, 0, False))

    if domain:
        p.add_argument('--domain',
            help="domain to use for this operation")
        #domain_argparser.set_defaults(domain=Delay
    return p


def argparse_parse(parser, args):
    namespace = parser.parse_args(args)
    main = getattr(namespace, 'main_func', None)
    if main is None:
        raise Exception("parser %r lacks a main method- internal bug.\nGot namespace %r\n"
            % (parser, namespace))
    namespace.prog = parser.prog
    return main, namespace

def convert_to_restrict(sequence, default=packages.AlwaysTrue):
    """Convert an iterable to a list of atoms, or return the default"""
    l = []
    try:
        for x in sequence:
            l.append(parserestrict.parse_match(x))
    except parserestrict.ParseError, e:
        raise optparse.OptionValueError("arg %r isn't a valid atom: %s"
            % (x, e))
    return l or [default]

def find_domains_from_path(config, path):
    path = osutils.normpath(osutils.abspath(path))
    for name, domain in config.domain.iteritems():
        root = getattr(domain, 'root', None)
        if root is None:
            continue
        root = osutils.normpath(osutils.abspath(root))
        if root == path:
            yield name, domain

def main(subcommands, args=None, outfile=None, errfile=None,
    script_name=None):
    """Function to use in an "if __name__ == '__main__'" block in a script.

    Takes one or more combinations of option parser and main func and
    runs them, taking care of exception handling and some other things.

    Any ConfigurationErrors raised from your function (by the config
    manager) are handled. Other exceptions are not (trigger a traceback).

    :type subcommands: mapping of string => (OptionParser class, main func)
    :param subcommands: available commands.
        The keys are a subcommand name or None for other/unknown/no subcommand.
        The values are tuples of OptionParser subclasses and functions called
        as main_func(config, out, err) with a L{Values} instance, two
        L{snakeoil.formatters.Formatter} instances for output (stdout)
        and errors (stderr). It should return an integer used as
        exit status or None as synonym for 0.
    :type args: sequence of strings
    :param args: arguments to parse, defaulting to C{sys.argv[1:]}.
    :type outfile: file-like object
    :param outfile: File to use for stdout, defaults to C{sys.stdout}.
    :type errfile: file-like object
    :param errfile: File to use for stderr, defaults to C{sys.stderr}.
    :type script_name: string
    :param script_name: basename of this script, defaults to the basename
        of C{sys.argv[0]}.
    """
    exitstatus = 1

    if outfile is None:
        outfile = sys.stdout
    if errfile is None:
        errfile = sys.stderr

    options = out = None
    try:
        if isinstance(subcommands, dict):
            main_func, options = optparse_parse(subcommands, args=args, script_name=script_name,
                errfile=errfile)
        else:
            main_func, options = argparse_parse(subcommands, args)

        if getattr(options, 'color', True):
            formatter_factory = formatters.get_formatter
        else:
            formatter_factory = formatters.PlainTextFormatter
        out = formatter_factory(outfile)
        err = formatter_factory(errfile)
        if logging.root.handlers:
            # Remove the default handler.
            logging.root.handlers.pop(0)
        logging.root.addHandler(FormattingHandler(err))
        exitstatus = main_func(options, out, err)
    except errors.ConfigurationError, e:
        if getattr(options, 'debug', False):
            raise
        errfile.write('Error in configuration:\n%s\n' % (e,))
    except KeyboardInterrupt:
        if getattr(options, 'debug', False):
            raise
    if out is not None:
        if exitstatus:
            out.title('%s failed' % (options.prog,))
        else:
            out.title('%s succeeded' % (options.prog,))
    raise MySystemExit(exitstatus)
