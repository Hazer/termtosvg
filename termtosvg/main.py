import argparse
import logging
import sys
import tempfile
from typing import List, Tuple, Union

import termtosvg.config as config

logger = logging.getLogger('termtosvg')

USAGE = """termtosvg [output_file] [--font FONT] [--theme THEME] [--screen-geometry GEOMETRY] [--verbose] [--help]
Record a terminal session and render an SVG animation on the fly
"""
EPILOG = "See also 'termtosvg record --help' and 'termtosvg render --help'"
RECORD_USAGE = "termtosvg record [output_file] [--screen-geometry GEOMETRY] [--verbose] [--help]"
RENDER_USAGE = "termtosvg render input_file [output_file] [--font FONT] [--theme THEME] " \
               "[--verbose] [--help]"


def parse(args, themes, templates):
    # type: (List) -> Tuple[Union[None, str], argparse.Namespace]
    # Usage: termtosvg  [output_file] [--font FONT] [--theme THEME] [--template TEMPLATE] [--screen-geometry GEOMETRY] [--verbose]
    font_parser = argparse.ArgumentParser(add_help=False)
    font_parser.add_argument(
        '--font',
        help="font to specify in the CSS portion of the SVG animation (DejaVu Sans Mono, "
             "Monaco...). If the font is not installed on the viewer's machine, the browser will"
             " display a default monospaced font instead.",
        metavar='FONT'
    )
    theme_parser = argparse.ArgumentParser(add_help=False)
    theme_parser.add_argument(
        '--theme',
        help='color theme used to render the terminal session ({})'.format(
            ', '.join(themes)),
        choices=themes,
        metavar='THEME'
    )
    template_parser = argparse.ArgumentParser(add_help=False)
    template_parser.add_argument(
        '--template',
        help='SVG template used for the animation ({})'.format(
            ', '.join(templates)),
        choices=templates,
        metavar='TEMPLATE'
    )
    geometry_parser = argparse.ArgumentParser(add_help=False)
    geometry_parser.add_argument(
        '--screen-geometry', '-g',
        help='geometry of the terminal screen used for rendering the animation. The geometry must '
        'be given as the number of columns and the number of rows on the screen separated by the '
        'character "x". For example "82x19" for an 82 columns by 19 rows screen',
        metavar='GEOMETRY',
        type=config.validate_geometry
    )
    verbose_parser = argparse.ArgumentParser(add_help=False)
    verbose_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='increase log messages verbosity'
    )
    parser = argparse.ArgumentParser(
        prog='termtosvg',
        parents=[font_parser, theme_parser, verbose_parser, geometry_parser, template_parser],
        usage=USAGE,
        epilog=EPILOG
    )
    parser.add_argument(
        'output_file',
        nargs='?',
        help='optional filename of the SVG animation; if missing, a random filename will be '
        'automatically generated',
        metavar='output_file'
    )
    if args:
        if args[0] == 'record':
            # Usage: termtosvg record [--verbose] [output_file]
            parser = argparse.ArgumentParser(
                description='record the session to a file in asciicast v2 format',
                parents=[geometry_parser, verbose_parser],
                usage=RECORD_USAGE
            )
            parser.add_argument(
                'output_file',
                nargs='?',
                help='optional filename for the recording; if missing, a random filename will '
                'be automatically generated'
            )
            return 'record', parser.parse_args(args[1:])
        elif args[0] == 'render':
            # Usage: termtosvg render [--font FONT] [--theme THEME] [--template TEMPLATE] [--screen-geometry GEOMETRY] [--verbose] input_file [output_file]
            parser = argparse.ArgumentParser(
                description='render an asciicast recording as an SVG animation',
                parents=[font_parser, theme_parser, template_parser, verbose_parser],
                usage=RENDER_USAGE
            )
            parser.add_argument(
                'input_file',
                help='recording of a terminal session in asciicast v1 or v2 format'
            )
            parser.add_argument(
                'output_file',
                nargs='?',
                help='optional filename for the SVG animation; if missing, a random filename will '
                'be automatically generated',
            )
            return 'render', parser.parse_args(args[1:])

    return None, parser.parse_args(args)


def record_subcommand(configuration, input_fileno, output_fileno, cast_filename):
    """Save a terminal session as an asciicast recording"""
    import termtosvg.term as term
    logger.info('Recording started, enter "exit" command or Control-D to end')
    geometry = configuration['global']['screen-geometry']
    if geometry is None:
        columns, lines = term.get_terminal_size(output_fileno)
    else:
        columns, lines = geometry
    with term.TerminalMode(input_fileno):
        records = term.record(columns, lines, input_fileno, output_fileno)
        with open(cast_filename, 'w') as cast_file:
            for record in records:
                print(record.to_json_line(), file=cast_file)
    logger.info('Recording ended, cast file is {}'.format(cast_filename))


def render_subcommand(configuration, cast_filename, svg_filename):
    """Render the animation from an asciicast recording"""
    import termtosvg.anim as anim
    import termtosvg.asciicast as asciicast
    import termtosvg.term as term

    logger.info('Rendering started')
    asciicast_records = asciicast.read_records(cast_filename)
    theme_name = configuration['global']['theme']
    theme = configuration.get(theme_name)
    geometry = configuration['global']['screen-geometry']
    records_with_theme = term.update_header(asciicast_records, theme)
    replayed_records = term.replay(records=records_with_theme,
                                   from_pyte_char=anim.CharacterCell.from_pyte)
    anim.render_animation(replayed_records, svg_filename, configuration['global']['font'])
    logger.info('Rendering ended, SVG animation is {}'.format(svg_filename))


def record_render_subcommand(configuration, input_fileno, output_fileno, svg_filename):
    """Record and render the animation on the fly"""
    import termtosvg.anim as anim
    import termtosvg.term as term

    logger.info('Recording started, enter "exit" command or Control-D to end')
    geometry = configuration['global']['screen-geometry']
    if geometry is None:
        columns, lines = term.get_terminal_size(output_fileno)
    else:
        columns, lines = geometry
    theme_name = configuration['global']['theme']
    theme = configuration.get(theme_name)
    with term.TerminalMode(input_fileno):
        asciicast_records = term.record(columns, lines, input_fileno, output_fileno)
        records_with_theme = term.update_header(asciicast_records, theme)
        replayed_records = term.replay(records=records_with_theme,
                                       from_pyte_char=anim.CharacterCell.from_pyte)
        anim.render_animation(replayed_records, svg_filename, configuration['global']['font'])
    logger.info('Recording ended, SVG animation is {}'.format(svg_filename))


def main(args=None, input_fileno=None, output_fileno=None):
    # type: (List, Union[int, None], Union[int, None]) -> None
    if args is None:
        args = sys.argv
    if input_fileno is None:
        input_fileno = sys.stdin.fileno()
    if output_fileno is None:
        output_fileno = sys.stdout.fileno()

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.handlers = [console_handler]
    logger.setLevel(logging.INFO)

    configuration, templates = config.init_read_conf()
    themes = config.CaseInsensitiveDict(**configuration)
    del themes['global']

    command, args = parse(args[1:], themes, templates)

    if args.verbose:
        _, log_filename = tempfile.mkstemp(prefix='termtosvg_', suffix='.log')
        file_handler = logging.FileHandler(filename=log_filename, mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        logger.handlers.append(file_handler)
        logger.info('Logging to {}'.format(log_filename))

    # Gather command line options in a dictionary in the same format as configuration['global']
    cli_options = {'font', 'screen_geometry', 'theme'}
    cli_options_values = {attribute.replace('_', '-'): args.__getattribute__(attribute)
                          for attribute in set.intersection(set(vars(args)), cli_options)
                          if args.__getattribute__(attribute) is not None}

    # Override static configuration with command line options
    configuration['global'].update(**cli_options_values)

    if command == 'record':
        cast_filename = args.output_file
        if cast_filename is None:
            _, cast_filename = tempfile.mkstemp(prefix='termtosvg_', suffix='.cast')
        record_subcommand(configuration, input_fileno, output_fileno, cast_filename)
    elif command == 'render':
        svg_filename = args.output_file
        if svg_filename is None:
            _, svg_filename = tempfile.mkstemp(prefix='termtosvg_', suffix='.svg')
        render_subcommand(configuration, args.input_file, svg_filename)
    else:
        svg_filename = args.output_file
        if svg_filename is None:
            _, svg_filename = tempfile.mkstemp(prefix='termtosvg_', suffix='.svg')

        record_render_subcommand(configuration, input_fileno, output_fileno, svg_filename)

    for handler in logger.handlers:
        handler.close()
